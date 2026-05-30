from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

from witty_service.application.backport_git_client import BackportGitClient


class BackportCvekitClient:
    REFRESH_META_SCHEMA_VERSION = 1
    STATIC_COMMIT_KEYS = {
        "commit",
        "input_commit",
        "commit_title",
        "committed_datetime",
        "target_branch",
    }
    PATCH_KIND_TO_KEY = {
        "original": "original_patch_path",
        "current": "patch_path",
        "backported": "backported_patch_path",
    }
    PATCH_KEYS = tuple(PATCH_KIND_TO_KEY.values())

    def __init__(
        self,
        *,
        runs_root: str | Path,
        openclaw_config_path: str | Path | None = None,
    ) -> None:
        self._runs_root = Path(runs_root).expanduser().resolve()
        self._openclaw_config_path = self._resolve_openclaw_config_path(openclaw_config_path)

    # ── 初始化 ──────────────────────────────────────────────────

    @staticmethod
    def _resolve_cvekit() -> Path:
        result = subprocess.run(
            ["which", "cvekit"],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        candidate = (result.stdout or "").strip()
        if result.returncode == 0 and candidate:
            path = Path(candidate).expanduser().resolve()
            if path.exists():
                return path
        raise RuntimeError("cvekit 不在 PATH 中")

    def _resolve_openclaw_config_path(self, config_path: str | Path | None) -> Path:
        path = config_path or os.environ.get("OPENCLAW_CONFIG_PATH") or "~/.openclaw/openclaw.json"
        return Path(path).expanduser().resolve(strict=False)

    # ── LLM 配置 ───────────────────────────────────────────────

    def _get_llm_config(self) -> dict[str, str]:
        config_path = self._openclaw_config_path
        try:
            with config_path.open("r", encoding="utf-8") as handle:
                config = json.load(handle)
        except Exception as error:
            raise RuntimeError(f"读取 openclaw.json 失败: {error}") from error
        if not isinstance(config, dict):
            raise RuntimeError(f"openclaw.json 顶层必须是对象: {config_path}")

        mcp_config = ((config.get("mcp") or {}).get("servers") or {}).get("cvekit_mcp")
        if not isinstance(mcp_config, dict):
            mcp_config = ((config.get("mcpServers") or {}).get("cvekit_mcp") or {})
        if not isinstance(mcp_config, dict):
            raise RuntimeError(f"openclaw.json 中缺少 cvekit_mcp 配置: {config_path}")

        args = mcp_config.get("args") or []
        if not isinstance(args, list):
            args = []
        env_config = mcp_config.get("env") or {}
        if not isinstance(env_config, dict):
            env_config = {}

        arg_values: dict[str, str] = {}
        option_names = {
            "--llm-provider",
            "--api-key",
            "--llm-base-url",
            "--llm-model-name",
        }
        index = 0
        while index < len(args):
            item = str(args[index]).strip()
            if item in option_names and index + 1 < len(args):
                value = str(args[index + 1]).strip()
                if value:
                    arg_values[item] = value
                index += 2
                continue
            for option_name in option_names:
                prefix = f"{option_name}="
                if item.startswith(prefix):
                    value = item[len(prefix) :].strip()
                    if value:
                        arg_values[option_name] = value
                    break
            index += 1

        selected_provider = (
            arg_values.get("--llm-provider")
            or str(env_config.get("LLM_PROVIDER") or "").strip()
        ).lower()
        api_key = (
            arg_values.get("--api-key")
            or str(env_config.get("API_KEY") or "").strip()
            or str(env_config.get("OPENAI_KEY") or "").strip()
        )
        base_url = (
            arg_values.get("--llm-base-url")
            or str(env_config.get("LLM_BASE_URL") or "").strip()
            or str(env_config.get("BASE_URL") or "").strip()
        )
        model_name = (
            arg_values.get("--llm-model-name")
            or str(env_config.get("LLM_MODEL_NAME") or "").strip()
            or str(env_config.get("MODEL_NAME") or "").strip()
        )
        if not selected_provider:
            raise RuntimeError(f"openclaw.json cvekit_mcp 缺少 --llm-provider 或 LLM_PROVIDER: {config_path}")
        if not api_key:
            raise RuntimeError(f"openclaw.json cvekit_mcp 缺少 --api-key 或 API_KEY: {config_path}")

        return {
            "provider": selected_provider,
            "api_key": api_key,
            "base_url": base_url,
            "model_name": model_name,
        }

    # ── 通用工具 ────────────────────────────────────────────────

    def _build_env(self) -> dict[str, str]:
        cvekit_bin_dir = self._resolve_cvekit().parent
        env: dict[str, str] = {
            "PATH": os.pathsep.join(
                [
                    str(cvekit_bin_dir),
                    "/usr/local/bin",
                    "/usr/bin",
                    "/usr/local/sbin",
                    "/usr/sbin",
                ]
            ),
        }
        for key in ("LANG", "LINUX_REPO_USE_CACHE_ONLY"):
            value = os.environ.get(key)
            if value:
                env[key] = value
        return env

    def _run_cvekit(self, args: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
        cmd_args = list(args)
        existing_options = {
            item.split("=", 1)[0]
            for item in cmd_args
            if isinstance(item, str) and item.startswith("--")
        }
        llm_config = self._get_llm_config()
        for option, value in (
            ("--llm-provider", llm_config.get("provider")),
            ("--llm-base-url", llm_config.get("base_url")),
            ("--llm-model-name", llm_config.get("model_name")),
            ("--api-key", llm_config.get("api_key")),
        ):
            if value and option not in existing_options:
                cmd_args.extend([option, value])

        cmd = [str(self._resolve_cvekit()), *cmd_args]
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "cvekit 执行失败\n"
                f"command: {' '.join(redacted_cmd)}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
        return result

    @staticmethod
    def _redact_command(cmd: list[str]) -> list[str]:
        redacted: list[str] = []
        skip_next = False
        for item in cmd:
            if skip_next:
                redacted.append("***")
                skip_next = False
                continue
            if item == "--api-key":
                redacted.append(item)
                skip_next = True
                continue
            if item.startswith("--api-key="):
                redacted.append("--api-key=***")
                continue
            redacted.append(item)
        return redacted

    @staticmethod
    def _parse_json_output(output: str) -> dict[str, Any]:
        text = (output or "").strip()
        if not text:
            return {}
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                return {}
            try:
                loaded = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _read_report(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise RuntimeError(f"report 内容不是合法 YAML 对象: {path}")
        data: dict[str, Any] = loaded
        commits = data.get("commits") or []
        if not isinstance(commits, list):
            commits = []
        return data, commits

    @staticmethod
    def _build_patch_meta(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
        patches: dict[str, dict[str, Any]] = {}
        for kind, key in BackportCvekitClient.PATCH_KIND_TO_KEY.items():
            raw_path = str(item.get(key) or "").strip()
            patch_file = Path(raw_path).expanduser() if raw_path else None
            patches[kind] = {
                "exists": bool(patch_file and patch_file.is_file()),
                "file_name": Path(raw_path).name if raw_path else "",
            }
        return patches

    @staticmethod
    def sanitize_commit_item(item: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(item)
        for key in BackportCvekitClient.PATCH_KEYS:
            sanitized.pop(key, None)
        sanitized["row_id"] = BackportCvekitClient._build_row_id(item)
        sanitized["patches"] = BackportCvekitClient._build_patch_meta(item)
        return sanitized

    @staticmethod
    def sanitize_commit_list(commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            BackportCvekitClient.sanitize_commit_item(item)
            for item in commits
            if isinstance(item, dict)
        ]

    @staticmethod
    def _overlay_commit(raw_row: dict[str, Any], row_overlay: dict[str, Any]) -> dict[str, Any]:
        merged = dict(raw_row)
        for key, value in row_overlay.items():
            if key in {"row_id", "patches"}:
                continue
            if key in BackportCvekitClient.PATCH_KEYS:
                continue
            merged[key] = value
        return merged

    def _resolve_commit_row(
        self,
        *,
        row: dict[str, Any],
        base_report_path: str,
        working_report_path: str | None = None,
    ) -> dict[str, Any]:
        target_row_id = self._build_row_id(row)
        candidate_paths: list[Path] = []
        for raw_path in (working_report_path, base_report_path):
            if not raw_path:
                continue
            resolved = Path(raw_path).expanduser().resolve()
            if resolved in candidate_paths:
                continue
            candidate_paths.append(resolved)

        for candidate in candidate_paths:
            if not candidate.exists():
                continue
            _, commits = self._read_report(candidate)
            for item in commits:
                if not isinstance(item, dict):
                    continue
                if self._build_row_id(item) == target_row_id:
                    return self._overlay_commit(item, row)

        searched = ", ".join(str(path) for path in candidate_paths) or "<empty>"
        raise ValueError(f"report 中找不到 row_id={target_row_id}，searched={searched}")

    # ── 用 target 仓 git 历史和本地 patch 检查刷新状态 ─────────

    @staticmethod
    def _patch_check_error(result: dict[str, str]) -> str:
        stderr = str(result.get("stderr") or "").strip()
        stdout = str(result.get("stdout") or "").strip()
        return stderr or stdout or "git apply --check failed"

    def _mark_merged_by_subject(
        self,
        report_data: dict[str, Any],
        subject_map: dict[str, str],
    ) -> int:
        commits = report_data.get("commits")
        if not isinstance(commits, list) or not commits:
            return 0

        marked_count = 0
        for item in commits:
            if not isinstance(item, dict):
                continue
            title = str(item.get("commit_title") or "").strip()
            matched_commit = subject_map.get(title) if title else None
            if not matched_commit:
                continue
            if item.get("merged_in_target") is not True:
                marked_count += 1
            item["merged_in_target"] = True
            item["merged_check_error"] = None
            item["has_conflict"] = False
            item["conflict_check_method"] = "target-log-subject"
            item["conflict_check_error"] = None
            item["status"] = "success"
            item["error"] = None
            if not str(item.get("applied_commit") or "").strip():
                item["applied_commit"] = matched_commit
        report_data["commits"] = commits
        return marked_count

    def _reconcile_report(self, report_data: dict[str, Any], target_path: str) -> dict[str, Any]:
        commits = report_data.get("commits")
        if not isinstance(commits, list) or not commits:
            return report_data
        subject_map = BackportGitClient.collect_subject_map(target_path)
        if not subject_map:
            return report_data
        self._mark_merged_by_subject(report_data, subject_map)
        return report_data

    @staticmethod
    def _refresh_meta(report_data: dict[str, Any]) -> dict[str, Any]:
        meta = report_data.get("refresh_meta")
        return meta if isinstance(meta, dict) else {}

    def _has_unchanged_target(self, report_data: dict[str, Any], target_state: dict[str, Any]) -> bool:
        meta = self._refresh_meta(report_data)
        return (
            meta.get("schema_version") == self.REFRESH_META_SCHEMA_VERSION
            and meta.get("target_path") == target_state.get("target_path")
            and meta.get("target_branch") == target_state.get("target_branch")
            and meta.get("target_head_checked") == target_state.get("target_head")
            and meta.get("target_status_clean") is True
            and target_state.get("target_status_clean") is True
        )

    def _write_refresh_meta(
        self,
        report_data: dict[str, Any],
        target_state: dict[str, Any],
        *,
        mode: str,
        checked_count: int,
        skipped_count: int,
        fallback_reason: str | None = None,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "schema_version": self.REFRESH_META_SCHEMA_VERSION,
            "target_path": target_state.get("target_path") or "",
            "target_branch": target_state.get("target_branch") or "",
            "target_head_checked": target_state.get("target_head") or "",
            "target_status_clean": bool(target_state.get("target_status_clean")),
            "refresh_mode": mode,
            "checked_count": checked_count,
            "skipped_count": skipped_count,
            "checked_at": int(time.time()),
        }
        if fallback_reason:
            meta["fallback_reason"] = fallback_reason
        report_data["refresh_meta"] = meta
        return report_data

    @staticmethod
    def _subject_map_from_commits(commits: list[dict[str, str]]) -> dict[str, str]:
        subject_map: dict[str, str] = {}
        for item in commits:
            subject = str(item.get("subject") or "").strip()
            commit_hash = str(item.get("hash") or "").strip()
            if subject and commit_hash and subject not in subject_map:
                subject_map[subject] = commit_hash
        return subject_map

    def _collect_refresh_subjects(
        self,
        report_data: dict[str, Any],
        target_path: str,
        target_state: dict[str, Any],
    ) -> tuple[dict[str, str], str]:
        meta = self._refresh_meta(report_data)
        old_head = str(meta.get("target_head_checked") or "").strip()
        new_head = str(target_state.get("target_head") or "").strip()
        if (
            old_head
            and new_head
            and old_head != new_head
            and meta.get("target_path") == target_state.get("target_path")
            and meta.get("target_branch") == target_state.get("target_branch")
        ):
            recent_commits = BackportGitClient.list_commits_between(target_path, old_head, new_head)
            subject_map = self._subject_map_from_commits(recent_commits)
            if subject_map:
                return subject_map, "head-range"

        return BackportGitClient.collect_subject_map(target_path), "recent-log"

    @staticmethod
    def _find_merged_prefix_len(commits: list[dict[str, Any]]) -> int:
        prefix_len = 0
        for item in commits:
            if item.get("merged_in_target") is True:
                prefix_len += 1
                continue
            break
        return prefix_len

    def _apply_local_patch_checks(
        self,
        *,
        rows_to_check: list[dict[str, Any]],
        target_path: str,
    ) -> None:
        for item in rows_to_check:
            if item.get("merged_in_target") is True:
                continue

            patch_path = str(item.get("original_patch_path") or "").strip()
            if not patch_path:
                raise ValueError(f"commit 缺少 original_patch_path: {self._build_row_id(item)}")

            try:
                reverse_result = BackportGitClient.check_patch_file(
                    target_path,
                    patch_path,
                    reverse=True,
                )
                if reverse_result.get("returncode") == "0":
                    item["merged_in_target"] = True
                    item["merged_check_error"] = None
                    item["has_conflict"] = False
                    item["conflict_check_method"] = "patch-reverse-check"
                    item["conflict_check_error"] = None
                    item["status"] = "success"
                    item["error"] = None
                    continue

                apply_result = BackportGitClient.check_patch_file(target_path, patch_path)
            except (FileNotFoundError, NotADirectoryError) as error:
                raise ValueError(str(error)) from error

            item["merged_in_target"] = False
            if apply_result.get("returncode") == "0":
                item["has_conflict"] = False
                item["conflict_check_method"] = "fast-apply"
                item["conflict_check_error"] = None
                item["status"] = "success"
                item["error"] = None
                if not str(item.get("patch_path") or "").strip():
                    item["patch_path"] = patch_path
            else:
                item["has_conflict"] = True
                item["conflict_check_method"] = "fast-apply"
                item["conflict_check_error"] = self._patch_check_error(apply_result)

    def _refresh_report_locally(
        self,
        report_data: dict[str, Any],
        target_path: str,
        target_state: dict[str, Any],
    ) -> tuple[dict[str, Any], str, int, int]:
        commits_raw = report_data.get("commits")
        if not isinstance(commits_raw, list) or not commits_raw:
            raise ValueError("report 中没有合法 commits")
        commits = [item for item in commits_raw if isinstance(item, dict)]
        if len(commits) != len(commits_raw):
            raise ValueError("report commits 结构不兼容")

        subject_map, subject_source = self._collect_refresh_subjects(
            report_data,
            target_path,
            target_state,
        )
        self._mark_merged_by_subject(report_data, subject_map)

        prefix_len = self._find_merged_prefix_len(commits)
        suffix = commits[prefix_len:]
        rows_to_check = [item for item in suffix if item.get("merged_in_target") is not True]
        mode = f"local-{subject_source}"

        self._apply_local_patch_checks(
            rows_to_check=rows_to_check,
            target_path=target_path,
        )
        report_data["commits"] = commits
        skipped_count = len(commits) - len(rows_to_check)
        self._write_refresh_meta(
            report_data,
            target_state,
            mode=mode,
            checked_count=len(rows_to_check),
            skipped_count=skipped_count,
        )
        return report_data, mode, len(rows_to_check), skipped_count

    def _refresh_report_with_cvekit(
        self,
        *,
        base_path: Path,
        report_data: dict[str, Any],
        commits: list[dict[str, Any]],
        target_path: str,
        fallback_reason: str,
    ) -> dict[str, Any]:
        env = self._build_env()

        self._runs_root.mkdir(parents=True, exist_ok=True)
        run_dir = Path(
            tempfile.mkdtemp(
                prefix=f"refresh_{int(time.time())}_",
                dir=str(self._runs_root),
            )
        )
        raw_config_path = run_dir / "refresh-backport-batch.yml"
        refreshed_path = run_dir / "refresh-backport-batch.yml.report.yml"

        raw_config = {key: value for key, value in report_data.items() if key not in {"commits", "refresh_meta"}}
        raw_config.pop("api_key", None)
        raw_config["commits"] = [
            item for item in (self._normalize_commit_item(commit) for commit in commits) if item
        ]
        with raw_config_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(raw_config, handle, allow_unicode=True, sort_keys=False)

        self._run_cvekit(
            ["--action", "backport-batch",
             "--backport-config", str(raw_config_path), "--debug", "--json"],
            env, run_dir,
        )

        if not refreshed_path.exists():
            raise RuntimeError(f"cvekit 执行后未生成刷新报告文件: {refreshed_path}")

        report_data, commits = self._read_report(refreshed_path)
        reconcile_target = str(report_data.get("target_path") or target_path or "")
        if reconcile_target:
            report_data = self._reconcile_report(report_data, reconcile_target)
            try:
                target_state = BackportGitClient.get_repo_state(reconcile_target)
                self._write_refresh_meta(
                    report_data,
                    target_state,
                    mode="cvekit-fallback",
                    checked_count=len(commits),
                    skipped_count=0,
                    fallback_reason=fallback_reason,
                )
            except (FileNotFoundError, NotADirectoryError, RuntimeError):
                pass
        with base_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(report_data, handle, allow_unicode=True, sort_keys=False)

        _, commits = self._read_report(base_path)
        return {
            "operation": "refresh_report",
            "status": "success",
            "stage": "interactive_editing",
            "summary": f"已刷新当前 report 状态，共 {len(commits)} 条 commit",
            "artifacts": {
                "base_report_path": str(base_path),
                "run_dir": str(run_dir),
                "refresh_mode": "cvekit-fallback",
                "fallback_reason": fallback_reason,
            },
            "report": {
                "report_path": str(base_path),
                "commit_count": len(commits),
                "commits": commits,
            },
        }

    @staticmethod
    def _normalize_commit_item(item: object) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {}
        return {
            key: item[key]
            for key in BackportCvekitClient.STATIC_COMMIT_KEYS
            if item.get(key) is not None
        }

    @staticmethod
    def _filtered_report_path(base_path: Path) -> Path:
        report_suffix = ".report.yml"
        if base_path.name.endswith(report_suffix):
            return base_path.with_name(f"{base_path.name[:-len(report_suffix)]}.filtered.report.yml")
        return base_path.with_name(f"{base_path.stem}.filtered{base_path.suffix}")

    @staticmethod
    def _infer_likely_missing_prerequisite(text: str) -> bool:
        lowered = text.lower()
        return any(
            keyword in lowered
            for keyword in (
                "missing prerequisite",
                "prerequisite",
                "depends on",
                "already exists in working directory",
                "patch does not apply",
            )
        )

    # ── 生成报告 ────────────────────────────────────────────────

    def generate_report(
        self,
        excel_path: str,
        project_url: str,
        project_dir: str,
        source_branch: str,
        target_path: str,
        target_release: str,
        patch_dataset_dir: str,
        signer_name: str,
        signer_email: str,
    ) -> dict[str, Any]:
        env = self._build_env()

        excel = Path(excel_path).expanduser().resolve()
        if not excel.exists():
            raise FileNotFoundError(f"excel_path 不存在: {excel}")
        excel_suffix = excel.suffix.lower()
        if excel_suffix not in {".xlsx", ".xls"}:
            raise ValueError(f"excel_path 不是 Excel 文件: {excel}")

        target_repo = Path(target_path).expanduser().resolve()
        BackportGitClient.ensure_git_repo(target_repo)

        self._runs_root.mkdir(parents=True, exist_ok=True)
        run_dir = Path(
            tempfile.mkdtemp(
                prefix=f"{os.getpid()}_{time.time_ns()}_",
                dir=str(self._runs_root),
            )
        )
        base_config_path = run_dir / "backport.base.yml"
        config_path = run_dir / "backport-batch.yml"
        report_path = run_dir / "backport-batch.yml.report.yml"

        base_config: dict[str, Any] = {
            "project": "linux",
            "target_path": str(target_repo),
        }
        for key, value in {
            "project_url": project_url,
            "project_dir": project_dir,
            "source_branch": source_branch,
            "target_release": target_release,
            "patch_dataset_dir": patch_dataset_dir,
            "signer_name": signer_name,
            "signer_email": signer_email,
        }.items():
            if isinstance(value, str) and value.strip():
                base_config[key] = value.strip()
        with base_config_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(base_config, handle, allow_unicode=True, sort_keys=False)

        self._run_cvekit(
            ["--action", "backport-batch",
             "--backport-excel", str(excel),
             "-o", str(config_path),
             "--backport-config", str(base_config_path)],
            env, run_dir,
        )

        self._run_cvekit(
            ["--action", "backport-batch",
            "--backport-config", str(config_path),
            "--debug", "--json"],
            env, run_dir,
        )

        if not report_path.exists():
            raise RuntimeError(f"cvekit 执行后未生成报告文件: {report_path}")

        report_data, commits = self._read_report(report_path)
        report_data = self._reconcile_report(report_data, str(target_repo))
        target_state = BackportGitClient.get_repo_state(str(target_repo))
        self._write_refresh_meta(
            report_data,
            target_state,
            mode="generate-report",
            checked_count=len(commits),
            skipped_count=0,
        )
        with report_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(report_data, handle, allow_unicode=True, sort_keys=False)

        _, commits = self._read_report(report_path)

        return {
            "operation": "generate_report",
            "status": "success",
            "stage": "interactive_editing",
            "summary": f"生成报告成功，共 {len(commits)} 条 commit",
            "artifacts": {
                "report_path": str(report_path),
                "config_path": str(config_path),
                "base_config_path": str(base_config_path),
                "run_dir": str(run_dir),
            },
            "report": {
                "report_path": str(report_path),
                "commit_count": len(commits),
                "commits": commits,
            },
        }

    # ── 刷新报告 ────────────────────────────────────────────────

    def refresh_report(
        self,
        base_report_path: str,
        target_path: str,
    ) -> dict[str, Any]:
        base_path = Path(base_report_path).expanduser().resolve()
        if not base_path.exists():
            raise FileNotFoundError(f"base_report_path 不存在: {base_path}")

        report_data, commits = self._read_report(base_path)
        if not commits:
            raise RuntimeError(f"report 中没有可刷新的 commits: {base_path}")

        reconcile_target = str(report_data.get("target_path") or target_path or "")
        if not reconcile_target:
            return self._refresh_report_with_cvekit(
                base_path=base_path,
                report_data=report_data,
                commits=commits,
                target_path=target_path,
                fallback_reason="missing target_path",
            )

        try:
            target_state = BackportGitClient.get_repo_state(reconcile_target)
        except (FileNotFoundError, NotADirectoryError, RuntimeError) as error:
            return self._refresh_report_with_cvekit(
                base_path=base_path,
                report_data=report_data,
                commits=commits,
                target_path=target_path,
                fallback_reason=str(error),
            )

        meta = self._refresh_meta(report_data)
        if meta.get("schema_version") == self.REFRESH_META_SCHEMA_VERSION:
            if meta.get("target_path") and meta.get("target_path") != target_state.get("target_path"):
                return self._refresh_report_with_cvekit(
                    base_path=base_path,
                    report_data=report_data,
                    commits=commits,
                    target_path=target_path,
                    fallback_reason="target_path changed",
                )
            if meta.get("target_branch") and meta.get("target_branch") != target_state.get("target_branch"):
                return self._refresh_report_with_cvekit(
                    base_path=base_path,
                    report_data=report_data,
                    commits=commits,
                    target_path=target_path,
                    fallback_reason="target_branch changed",
                )

        if self._has_unchanged_target(report_data, target_state):
            return {
                "operation": "refresh_report",
                "status": "success",
                "stage": "interactive_editing",
                "summary": f"目标仓无变化，直接复用当前 report，共 {len(commits)} 条 commit",
                "artifacts": {
                    "base_report_path": str(base_path),
                    "refresh_mode": "no-change",
                },
                "report": {
                    "report_path": str(base_path),
                    "commit_count": len(commits),
                    "commits": commits,
                },
            }

        try:
            report_data, mode, checked_count, skipped_count = self._refresh_report_locally(
                report_data,
                reconcile_target,
                target_state,
            )
        except ValueError as error:
            return self._refresh_report_with_cvekit(
                base_path=base_path,
                report_data=report_data,
                commits=commits,
                target_path=target_path,
                fallback_reason=str(error),
            )

        with base_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(report_data, handle, allow_unicode=True, sort_keys=False)
        _, commits = self._read_report(base_path)

        return {
            "operation": "refresh_report",
            "status": "success",
            "stage": "interactive_editing",
            "summary": f"已快速刷新当前 report，检查 {checked_count} 条，跳过 {skipped_count} 条",
            "artifacts": {
                "base_report_path": str(base_path),
                "refresh_mode": mode,
                "checked_count": checked_count,
                "skipped_count": skipped_count,
            },
            "report": {
                "report_path": str(base_path),
                "commit_count": len(commits),
                "commits": commits,
            },
        }

    # ── 执行选中 commit ────────────────────────────────────────

    def execute_selected(
        self,
        base_report_path: str,
        selected_commits: list[dict[str, Any]],
        target_path: str,
        patch_dataset_dir: str,
        signer_name: str,
        signer_email: str,
        working_report_path: str | None = None,
    ) -> dict[str, Any]:
        env = self._build_env()
        base_path = Path(base_report_path).expanduser().resolve()
        if not base_path.exists():
            raise FileNotFoundError(f"base_report_path 不存在: {base_path}")

        orig_report, _ = self._read_report(base_path)
        if not selected_commits:
            raise ValueError("selected_commits 为空")

        filtered_report_path = self._filtered_report_path(base_path)

        resolved_commits = [
            self._resolve_commit_row(
                row=item,
                base_report_path=base_report_path,
                working_report_path=working_report_path,
            )
            for item in selected_commits
            if isinstance(item, dict)
        ]
        if not resolved_commits:
            raise ValueError("selected_commits 解析后为空")

        actionable_commits = [
            item
            for item in resolved_commits
            if item.get("merged_in_target") is not True
            and item.get("empty_patch") is not True
            and item.get("equivalent_exists") is not True
            and str(item.get("status") or "").strip().lower() != "skipped"
            and str(item.get("merged_in_target") or "").strip().lower() != "skipped"
        ]
        if not actionable_commits:
            return {
                "operation": "execute_selected",
                "status": "success",
                "stage": "interactive_editing",
                "summary": f"选中的 {len(resolved_commits)} 条 commit 均无需执行",
                "report": {
                    "commit_count": len(resolved_commits),
                    "commits": resolved_commits,
                },
                "diagnostics": {
                    "likely_missing_prerequisite": False,
                },
            }

        config_data = dict(orig_report)
        config_data["commits"] = actionable_commits
        config_data.pop("api_key", None)
        if patch_dataset_dir.strip():
            config_data["patch_dataset_dir"] = patch_dataset_dir.strip()
        if signer_name.strip():
            config_data["signer_name"] = signer_name.strip()
        if signer_email.strip():
            config_data["signer_email"] = signer_email.strip()
        if target_path.strip():
            config_data["target_path"] = target_path.strip()
        with filtered_report_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(config_data, handle, allow_unicode=True, sort_keys=False)

        cmd = [
            "--action", "backport-batch",
            "--backport-config", str(filtered_report_path),
            "-e", "--debug", "--json",
        ]
        result = self._run_cvekit(cmd, env, filtered_report_path.parent)
        combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part)

        _, commits = self._read_report(filtered_report_path)
        return {
            "operation": "execute_selected",
            "status": "success",
            "stage": "interactive_editing",
            "summary": f"执行完成，共处理 {len(commits)} 条 commit",
            "artifacts": {
                "filtered_report_path": str(filtered_report_path),
            },
            "report": {
                "commit_count": len(commits),
                "commits": commits,
            },
            "diagnostics": {
                "likely_missing_prerequisite": self._infer_likely_missing_prerequisite(combined_output),
            },
        }

    # ── 单条 apply ─────────────────────────────────────────────

    def apply_row(
        self,
        base_report_path: str,
        row: dict[str, Any],
        working_report_path: str | None = None,
    ) -> dict[str, Any]:
        env = self._build_env()
        base_path = Path(base_report_path).expanduser().resolve()
        if not base_path.exists():
            raise FileNotFoundError(f"base_report_path 不存在: {base_path}")
        apply_config_path = base_path
        if working_report_path:
            candidate_apply_path = Path(working_report_path).expanduser().resolve()
            if candidate_apply_path.exists():
                apply_config_path = candidate_apply_path

        resolved_row = self._resolve_commit_row(
            row=row,
            base_report_path=base_report_path,
            working_report_path=working_report_path,
        )
        if (
            resolved_row.get("merged_in_target") is True
            or resolved_row.get("empty_patch") is True
            or resolved_row.get("equivalent_exists") is True
            or str(resolved_row.get("status") or "").strip().lower() == "skipped"
            or str(resolved_row.get("merged_in_target") or "").strip().lower() == "skipped"
        ):
            return {
                "operation": "apply_row",
                "status": "success",
                "stage": "interactive_editing",
                "summary": "该提交无需执行",
                "report": {"commit_count": 1, "commits": [resolved_row]},
            }
        apply_value = self._resolve_apply_value(resolved_row)
        target_row_id = self._build_row_id(resolved_row)

        result = self._run_cvekit(
            ["--action", "backport-batch",
             "--backport-config", str(apply_config_path), "--debug", "--json",
             "--apply", apply_value],
            env, apply_config_path.parent,
        )
        apply_result = self._parse_json_output(result.stdout)

        _, commits = self._read_report(apply_config_path)
        affected_rows = [c for c in commits if isinstance(c, dict) and self._build_row_id(c) == target_row_id] or [resolved_row]
        apply_status = str(apply_result.get("status") or "").strip().lower()
        if apply_status and apply_status != "success":
            affected_rows = [
                {
                    **row,
                    "status": apply_status,
                    "error": apply_result.get("error") or row.get("error"),
                    "conflict_check_method": row.get("conflict_check_method") or "apply",
                    "conflict_check_error": apply_result.get("error") or row.get("conflict_check_error"),
                }
                for row in affected_rows
            ]

        return {
            "operation": "apply_row",
            "status": "failed" if apply_status == "failed" else "success",
            "stage": "interactive_editing",
            "summary": apply_result.get("error") or "单条应用执行完成",
            "report": {"commit_count": len(affected_rows), "commits": affected_rows},
        }

    def load_patch_preview(
        self,
        *,
        base_report_path: str,
        row: dict[str, Any],
        patch_kind: str,
        working_report_path: str | None = None,
    ) -> dict[str, Any]:
        if patch_kind not in self.PATCH_KIND_TO_KEY:
            raise ValueError(f"不支持的 patch_kind: {patch_kind}")

        resolved_row = self._resolve_commit_row(
            row=row,
            base_report_path=base_report_path,
            working_report_path=working_report_path,
        )
        patch_path = str(resolved_row.get(self.PATCH_KIND_TO_KEY[patch_kind]) or "").strip()
        if not patch_path:
            raise FileNotFoundError(f"{patch_kind} patch 不存在")

        patch_file = Path(patch_path).expanduser().resolve()
        if not patch_file.exists():
            raise FileNotFoundError(f"patch 文件不存在: {patch_file}")

        patch_text = patch_file.read_text(encoding="utf-8")
        return {
            "operation": "load_patch_preview",
            "status": "success",
            "patch": {
                "kind": patch_kind,
                "file_name": patch_file.name,
                "patch_text": patch_text,
                "size_bytes": patch_file.stat().st_size,
            },
        }

    @staticmethod
    def _resolve_apply_value(row: dict[str, Any]) -> str:
        for key in ("backported_patch_path", "patch_path", "original_patch_path", "commit", "input_commit"):
            val = row.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        raise ValueError(f"row 中缺少可用于 apply 的字段: {list(row.keys())}")

    @staticmethod
    def _build_row_id(row: dict[str, Any]) -> str:
        for key in ("row_id", "commit", "input_commit", "original_patch_path", "patch_path", "backported_patch_path"):
            val = row.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return json.dumps(row, ensure_ascii=False, sort_keys=True)
