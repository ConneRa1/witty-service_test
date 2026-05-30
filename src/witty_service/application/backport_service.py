from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from witty_service.api.services import ServiceContainer
from witty_service.application.backport_cvekit_client import BackportCvekitClient
from witty_service.application.backport_git_client import BackportGitClient
from witty_service.domain.errors import DomainError


logger = logging.getLogger(__name__)


def _default_config() -> dict[str, str]:
    return {
        "project_url": "",
        "project_dir": "",
        "source_branch": "",
        "target_path": "",
        "target_release": "",
        "patch_dataset_dir": "",
        "signer_name": "",
        "signer_email": "",
        "current_excel_path": "",
        "current_report_path": "",
        "current_filtered_report_path": "",
    }


class BackportService:
    def __init__(self, services: ServiceContainer) -> None:
        self._config_path = services.workspace_store.base_dir / "config" / "backport.json"
        self._git_client = BackportGitClient()
        self._cvekit_client = BackportCvekitClient(
            runs_root=services.workspace_store.base_dir / "backport-runs",
        )

    def get_config(self) -> dict[str, str]:
        if not self._config_path.exists():
            logger.info("Backport config not found, using defaults: path=%s", self._config_path)
            return _default_config()

        try:
            loaded = json.loads(self._config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DomainError(
                code="BACKPORT_CONFIG_LOAD_FAILED",
                message="Backport config is invalid.",
                details={"path": str(self._config_path), "error": str(exc)},
            ) from exc

        config = _default_config()
        for key in config:
            value = loaded.get(key, "")
            config[key] = value if isinstance(value, str) else ""
        logger.info(
            "Backport config loaded: path=%s target_path=%s target_release=%s current_report=%s",
            self._config_path,
            config["target_path"],
            config["target_release"],
            config["current_report_path"],
        )
        return config

    def update_config(self, payload: dict[str, str]) -> None:
        config = _default_config()
        for key in config:
            value = payload.get(key, "")
            config[key] = value.strip() if isinstance(value, str) else ""

        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(
            "Backport config saved: path=%s target_path=%s target_release=%s excel=%s report=%s",
            self._config_path,
            config["target_path"],
            config["target_release"],
            config["current_excel_path"],
            config["current_report_path"],
        )

    @property
    def config_path(self) -> str:
        return str(self._config_path)

    def browse_path(self, raw_path: str | None = None) -> dict[str, Any]:
        root = Path.home().resolve()
        current_path = Path(raw_path or root).expanduser().resolve()
        try:
            current_path.relative_to(root)
        except ValueError as exc:
            raise DomainError(
                code="BACKPORT_BROWSE_PATH_FORBIDDEN",
                message="Backport browse path is outside the allowed root.",
                details={"path": str(current_path), "root": str(root)},
            ) from exc

        if current_path.is_file():
            current_path = current_path.parent

        if not current_path.is_dir():
            raise DomainError(
                code="BACKPORT_BROWSE_PATH_INVALID",
                message="Backport browse path is not a directory.",
                details={"path": str(current_path)},
            )

        entries = [
            {"name": item.name, "path": str(item), "is_dir": item.is_dir()}
            for item in sorted(current_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        ]
        parent_path = str(current_path.parent) if current_path != root else None
        return {"current_path": str(current_path), "parent_path": parent_path, "entries": entries}

    def run_action(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_action = action.strip()
        handlers = self._build_handlers()
        handler = handlers.get(normalized_action)
        if handler is None:
            raise DomainError(
                code="BACKPORT_ACTION_NOT_SUPPORTED",
                message="Backport action is not supported.",
                details={"action": normalized_action or action},
            )
        normalized_payload = payload if isinstance(payload, dict) else {}
        started_at = time.monotonic()
        logger.info(
            "Backport action started: action=%s payload_keys=%s",
            normalized_action,
            sorted(normalized_payload.keys()),
        )
        try:
            parsed_result = handler(normalized_payload)
            self._persist_runtime_state(normalized_action, normalized_payload, parsed_result)
            elapsed = time.monotonic() - started_at
            status = parsed_result.get("status")
            logger.info(
                "Backport action completed: action=%s status=%s elapsed=%.2fs",
                normalized_action,
                status,
                elapsed,
            )
            return self._build_response(parsed_result)
        except Exception:
            logger.exception(
                "Backport action failed before response: action=%s elapsed=%.2fs",
                normalized_action,
                time.monotonic() - started_at,
            )
            raise

    def _build_handlers(self) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
        return {
            "generate_report": self._run_generate_report,
            "refresh_report": self._run_refresh_report,
            "load_git_log": self._run_load_git_log,
            "load_git_show": self._run_load_git_show,
            "load_patch_preview": self._run_load_patch_preview,
            "execute_selected": self._run_execute_selected,
            "apply_row": self._run_apply_row,
            "check_manual_patch": self._run_check_manual_patch,
            "apply_manual_patch": self._run_apply_manual_patch,
        }

    # ── 业务方法 ──────────────────────────────────────────────

    def _run_generate_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._extract_config(payload)
        excel_path = self._require_string(payload, "generate_report", "excel_path", "excelPath")
        logger.info(
            "Backport generate_report inputs: excel=%s project_dir=%s source_branch=%s target_path=%s target_release=%s patch_dataset_dir=%s",
            excel_path,
            config["project_dir"],
            config["source_branch"],
            config["target_path"],
            config["target_release"],
            config["patch_dataset_dir"],
        )
        try:
            return self._cvekit_client.generate_report(
                excel_path=excel_path,
                project_url=config["project_url"],
                project_dir=config["project_dir"],
                source_branch=config["source_branch"],
                target_path=config["target_path"],
                target_release=config["target_release"],
                patch_dataset_dir=config["patch_dataset_dir"],
                signer_name=config["signer_name"],
                signer_email=config["signer_email"],
            )
        except (RuntimeError, FileNotFoundError, NotADirectoryError, ValueError) as error:
            logger.exception("generate_report failed")
            return {
                "operation": "generate_report",
                "status": "failed",
                "summary": str(error),
                "diagnostics": {"error_text": str(error)},
            }

    def _run_refresh_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._extract_config(payload)
        base_report_path = self._get_string(payload, "base_report_path", "baseReportPath") or config["current_report_path"]
        if not base_report_path:
            raise DomainError(
                code="BACKPORT_ARGUMENT_REQUIRED",
                message="Missing required argument for refresh_report.",
                details={"action": "refresh_report", "keys": ["base_report_path", "baseReportPath"]},
            )
        try:
            return self._cvekit_client.refresh_report(
                base_report_path=base_report_path,
                target_path=config["target_path"],
            )
        except (RuntimeError, FileNotFoundError) as error:
            logger.exception("refresh_report failed")
            return {
                "operation": "refresh_report",
                "status": "failed",
                "summary": str(error),
                "diagnostics": {"error_text": str(error)},
            }

    def _run_load_git_log(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._extract_config(payload)
        try:
            target_path = self._resolve_target_path(payload, config, operation="load_git_log")
            entries = self._git_client.load_git_log(target_path, limit=100)
            return {
                "operation": "load_git_log",
                "status": "success",
                "summary": f"loaded {len(entries)} commits",
                "git": {"entries": entries},
            }
        except (DomainError, FileNotFoundError, NotADirectoryError) as error:
            logger.exception("load_git_log failed")
            return {
                "operation": "load_git_log",
                "status": "failed",
                "summary": str(error),
                "diagnostics": {"error_text": str(error)},
            }

    def _run_load_git_show(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._extract_config(payload)
        try:
            target_path = self._resolve_target_path(payload, config, operation="load_git_show")
            revision = self._require_string(payload, "load_git_show", "revision")
            show_content = self._git_client.load_git_show(target_path, revision)
            return {
                "operation": "load_git_show",
                "status": "success",
                "git": {
                    "revision": revision,
                    "show_content": show_content,
                },
            }
        except (DomainError, RuntimeError, FileNotFoundError, NotADirectoryError) as error:
            logger.exception("load_git_show failed")
            return {
                "operation": "load_git_show",
                "status": "failed",
                "summary": str(error),
                "diagnostics": {"error_text": str(error)},
            }

    def _run_execute_selected(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._extract_config(payload)
        base_report_path = self._require_string(payload, "execute_selected", "base_report_path", "baseReportPath")
        working_report_path = self._get_string(
            payload,
            "working_report_path",
            "workingReportPath",
            "current_filtered_report_path",
            "currentFilteredReportPath",
        )
        selected_commits = payload.get("selected_commits")
        if not isinstance(selected_commits, list) or not selected_commits:
            raise DomainError(
                code="BACKPORT_SELECTED_COMMITS_INVALID",
                message="selected_commits must be a non-empty array.",
                details={"action": "execute_selected"},
            )
        try:
            return self._cvekit_client.execute_selected(
                base_report_path=base_report_path,
                selected_commits=selected_commits,
                target_path=self._resolve_target_path(payload, config, operation="execute_selected"),
                patch_dataset_dir=config["patch_dataset_dir"],
                signer_name=config["signer_name"],
                signer_email=config["signer_email"],
                working_report_path=working_report_path,
            )
        except (RuntimeError, FileNotFoundError, ValueError) as error:
            logger.exception("execute_selected failed")
            return {
                "operation": "execute_selected",
                "status": "failed",
                "summary": str(error),
                "diagnostics": {"error_text": str(error)},
            }

    def _run_apply_row(self, payload: dict[str, Any]) -> dict[str, Any]:
        base_report_path = self._require_string(payload, "apply_row", "base_report_path", "baseReportPath")
        working_report_path = self._get_string(
            payload,
            "working_report_path",
            "workingReportPath",
            "current_filtered_report_path",
            "currentFilteredReportPath",
        )
        row = payload.get("row")
        if not isinstance(row, dict) or not row:
            raise DomainError(
                code="BACKPORT_ROW_INVALID",
                message="row must be a non-empty object.",
                details={"action": "apply_row"},
            )
        try:
            return self._cvekit_client.apply_row(
                base_report_path=base_report_path,
                row=row,
                working_report_path=working_report_path,
            )
        except (RuntimeError, FileNotFoundError, ValueError) as error:
            logger.exception("apply_row failed")
            failed_row = dict(row)
            failed_row["status"] = "failed"
            failed_row["error"] = str(error)
            return {
                "operation": "apply_row",
                "status": "failed",
                "summary": str(error),
                "diagnostics": {"error_text": str(error)},
                "report": {"commit_count": 1, "commits": [failed_row]},
            }

    def _run_check_manual_patch(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._extract_config(payload)
        try:
            target_path = self._resolve_target_path(payload, config, operation="check_manual_patch")
            patch_text = self._require_string(payload, "check_manual_patch", "patch_text", "patchText")
            result = self._git_client.check_manual_patch(target_path, patch_text)
            ok = result["returncode"] == "0"
            return {
                "operation": "check_manual_patch",
                "status": "success" if ok else "failed",
                "summary": "手动 Patch 可以干净应用" if ok else "手动 Patch 检查失败",
                "manual_patch": result,
                "diagnostics": {"error_text": result["stderr"]} if not ok else {},
            }
        except (DomainError, RuntimeError, FileNotFoundError, NotADirectoryError, ValueError) as error:
            logger.exception("check_manual_patch failed")
            return {
                "operation": "check_manual_patch",
                "status": "failed",
                "summary": str(error),
                "diagnostics": {"error_text": str(error)},
            }

    def _run_apply_manual_patch(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._extract_config(payload)
        try:
            target_path = self._resolve_target_path(payload, config, operation="apply_manual_patch")
            patch_text = self._require_string(payload, "apply_manual_patch", "patch_text", "patchText")
            result = self._git_client.apply_manual_patch(target_path, patch_text)
            ok = result["returncode"] == "0"
            return {
                "operation": "apply_manual_patch",
                "status": "success" if ok else "failed",
                "summary": "手动 Patch 已应用到目标仓" if ok else "手动 Patch 应用失败",
                "manual_patch": result,
                "diagnostics": {"error_text": result["stderr"]} if not ok else {},
            }
        except (DomainError, RuntimeError, FileNotFoundError, NotADirectoryError, ValueError) as error:
            logger.exception("apply_manual_patch failed")
            return {
                "operation": "apply_manual_patch",
                "status": "failed",
                "summary": str(error),
                "diagnostics": {"error_text": str(error)},
            }

    def _run_load_patch_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        base_report_path = self._require_string(payload, "load_patch_preview", "base_report_path", "baseReportPath")
        working_report_path = self._get_string(
            payload,
            "working_report_path",
            "workingReportPath",
            "current_filtered_report_path",
            "currentFilteredReportPath",
        )
        patch_kind = self._require_string(payload, "load_patch_preview", "patch_kind", "patchKind")
        row = payload.get("row")
        if not isinstance(row, dict) or not row:
            raise DomainError(
                code="BACKPORT_ROW_INVALID",
                message="row must be a non-empty object.",
                details={"action": "load_patch_preview"},
            )
        try:
            return self._cvekit_client.load_patch_preview(
                base_report_path=base_report_path,
                working_report_path=working_report_path,
                row=row,
                patch_kind=patch_kind,
            )
        except (RuntimeError, FileNotFoundError, ValueError) as error:
            logger.exception("load_patch_preview failed")
            return {
                "operation": "load_patch_preview",
                "status": "failed",
                "summary": str(error),
                "diagnostics": {"error_text": str(error)},
            }

    # ── 辅助方法 ──────────────────────────────────────────────

    def _extract_config(self, payload: dict[str, Any]) -> dict[str, str]:
        raw_config = payload.get("config")
        normalized = self.get_config()
        if not isinstance(raw_config, dict):
            return normalized

        for key in _default_config():
            value = raw_config.get(key)
            if isinstance(value, str):
                stripped = value.strip()
                if stripped or key.startswith("current_"):
                    normalized[key] = stripped
        return normalized

    def _persist_runtime_state(
        self,
        action: str,
        payload: dict[str, Any],
        parsed_result: dict[str, Any],
    ) -> None:
        report = parsed_result.get("report")
        if not isinstance(report, dict):
            report = {}
        artifacts = parsed_result.get("artifacts")
        if not isinstance(artifacts, dict):
            artifacts = {}

        config = self.get_config()
        if action == "generate_report":
            config["current_excel_path"] = self._get_string(payload, "excel_path", "excelPath")
            config["current_filtered_report_path"] = ""

        report_path = (
            self._get_string(artifacts, "base_report_path")
            or self._get_string(artifacts, "report_path")
            or self._get_string(report, "report_path")
        )
        if action in {"generate_report", "refresh_report"} and report_path:
            config["current_report_path"] = report_path

        filtered_report_path = self._get_string(artifacts, "filtered_report_path")
        if action == "execute_selected" and filtered_report_path:
            config["current_filtered_report_path"] = filtered_report_path
        self.update_config(config)

    def _require_string(self, payload: dict[str, Any], operation: str, *keys: str) -> str:
        value = self._get_string(payload, *keys)
        if value:
            return value
        raise DomainError(
            code="BACKPORT_ARGUMENT_REQUIRED",
            message=f"Missing required argument for {operation}.",
            details={"action": operation, "keys": list(keys)},
        )

    @staticmethod
    def _get_string(payload: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _resolve_target_path(
        self,
        payload: dict[str, Any],
        config: dict[str, str],
        *,
        operation: str,
    ) -> str:
        target_path = self._get_string(payload, "target_path", "targetPath") or config["target_path"]
        if target_path:
            return target_path
        raise DomainError(
            code="BACKPORT_TARGET_PATH_REQUIRED",
            message="target_path is required.",
            details={"action": operation},
        )

    # ── 响应格式 ──────────────────────────────────────────────

    def _build_response(self, parsed_result: dict[str, Any]) -> dict[str, Any]:
        sanitized_result = self._sanitize_parsed_result(parsed_result)
        operation = sanitized_result.get("operation", "unknown")
        is_error = sanitized_result.get("status") == "failed"
        if operation == "load_patch_preview":
            return {
                "agentId": "backport-direct",
                "agentName": "backport-direct-api",
                "sessionId": f"direct-{int(time.time() * 1000)}",
                "assistantText": "",
                "parsedResult": sanitized_result,
                "toolSnapshots": [],
            }

        combined_output = json.dumps(sanitized_result, ensure_ascii=False, indent=2)
        return {
            "agentId": "backport-direct",
            "agentName": "backport-direct-api",
            "sessionId": f"direct-{int(time.time() * 1000)}",
            "assistantText": self._build_assistant_text(sanitized_result),
            "parsedResult": sanitized_result,
            "toolSnapshots": [
                {
                    "tool_name": f"backport.{operation}",
                    "arguments_text": combined_output,
                    "response_text": combined_output,
                    "is_error": is_error,
                }
            ],
        }

    def _sanitize_parsed_result(self, parsed_result: dict[str, Any]) -> dict[str, Any]:
        sanitized = json.loads(json.dumps(parsed_result, ensure_ascii=False))
        report = sanitized.get("report")
        if not isinstance(report, dict):
            return sanitized
        commits = report.get("commits")
        if not isinstance(commits, list):
            return sanitized
        report["commits"] = self._cvekit_client.sanitize_commit_list(commits)
        sanitized["report"] = report
        return sanitized

    @staticmethod
    def _build_assistant_text(parsed_result: dict[str, Any] | None) -> str:
        if parsed_result is None:
            return ""
        return "<backport_result>\n" + json.dumps(parsed_result, ensure_ascii=False, indent=2) + "\n</backport_result>"
