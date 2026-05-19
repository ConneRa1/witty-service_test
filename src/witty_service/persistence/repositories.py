from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from witty_service.domain.enums import AgentStatus
from witty_service.persistence.orm import (
    AgentORM,
    AgentSkillORM,
    AgentRuntimeStateORM,
    MessageEventORM,
    MessageORM,
    ModelORM,
    SessionORM,
    SessionStatus,
    SkillORM,
    SkillRepositoryORM,
)
from witty_service.sandbox.base import SandboxHandle


@dataclass(slots=True)
class AgentRecord:
    id: str
    name: str
    description: str
    sandbox_type: str
    adapter_type: str
    status: AgentStatus
    sandbox_id: str | None
    workspace_path: str
    idle_timeout_seconds: int
    has_scheduled_tasks: bool
    last_active_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class ModelRecord:
    id: str
    name: str
    provider: str
    api_key: str
    api_base_url: str | None
    description: str
    enabled: bool
    max_tokens: int
    temperature: float
    is_default: bool
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class SessionRecord:
    id: str
    agent_id: str
    remote_runtime_agent_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class SandboxStateRecord:
    agent_id: str
    sandbox_payload_json: dict[str, Any]
    adapter_base_url: str | None
    adapter_ready: bool
    last_error: str | None

    @property
    def handle(self) -> SandboxHandle:
        payload = dict(self.sandbox_payload_json)
        return SandboxHandle(
            sandbox_id=str(payload["sandbox_id"]),
            agent_id=str(payload.get("agent_id", self.agent_id)),
            workspace_path=str(payload["workspace_path"]),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class SkillRepositoryRecord:
    repo_id: str
    repo_name: str
    source_type: str
    branch: str | None
    url: str | None
    local_path: str | None
    skill_discover_status: str
    skill_num: int
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class SkillRecord:
    skill_id: str
    repo_id: str | None
    skill_name: str
    relative_path: str | None
    metadata: dict[str, Any]
    skill_source: str | None
    skill_md_url: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class AgentSkillRecord:
    agent_id: str
    skill_id: str
    source_type: str
    repo_id: str | None
    skill_name: str
    installed_at: datetime
    relative_path: str | None = None
    metadata: dict[str, Any] | None = None
    skill_source: str | None = None
    skill_md_url: str | None = None


class SqliteRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_agent(
        self,
        *,
        name: str,
        sandbox_type: str,
        adapter_type: str,
        workspace_path: str,
        idle_timeout_seconds: int,
        description: str = "",
        status: AgentStatus | str = AgentStatus.creating,
        sandbox_id: str | None = None,
        has_scheduled_tasks: bool = False,
        last_active_at: datetime | None = None,
    ) -> AgentRecord:
        return self.create_agent_with_id(
            agent_id=str(uuid4()),
            name=name,
            sandbox_type=sandbox_type,
            adapter_type=adapter_type,
            workspace_path=workspace_path,
            idle_timeout_seconds=idle_timeout_seconds,
            description=description,
            status=status,
            sandbox_id=sandbox_id,
            has_scheduled_tasks=has_scheduled_tasks,
            last_active_at=last_active_at,
        )

    def create_agent_with_id(
        self,
        *,
        agent_id: str,
        name: str,
        sandbox_type: str,
        adapter_type: str,
        workspace_path: str,
        idle_timeout_seconds: int,
        description: str = "",
        status: AgentStatus | str = AgentStatus.creating,
        sandbox_id: str | None = None,
        has_scheduled_tasks: bool = False,
        last_active_at: datetime | None = None,
    ) -> AgentRecord:
        with self._session_factory() as session:
            row = AgentORM(
                id=agent_id,
                name=name,
                description=description,
                sandbox_type=sandbox_type,
                adapter_type=adapter_type,
                status=self._serialize_status(status),
                sandbox_id=sandbox_id,
                workspace_path=workspace_path,
                idle_timeout_seconds=idle_timeout_seconds,
                has_scheduled_tasks=has_scheduled_tasks,
                last_active_at=last_active_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._to_agent_record(row)

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        with self._session_factory() as session:
            row = session.get(AgentORM, agent_id)
            if row is None:
                return None
            return self._to_agent_record(row)

    def list_agents(self) -> list[AgentRecord]:
        with self._session_factory() as session:
            rows = (
                session.query(AgentORM)
                .filter(AgentORM.status != AgentStatus.deleted.value)
                .order_by(AgentORM.created_at.asc())
                .all()
            )
            return [self._to_agent_record(row) for row in rows]

    def update_agent_status(
        self,
        agent_id: str,
        status: AgentStatus | str,
        updated_at: datetime | None = None,
    ) -> AgentRecord:
        with self._session_factory() as session:
            row = session.get(AgentORM, agent_id)
            if row is None:
                raise KeyError(f"Agent not found: {agent_id}")
            row.status = self._serialize_status(status)
            if updated_at is not None:
                row.updated_at = updated_at
            session.commit()
            session.refresh(row)
            return self._to_agent_record(row)

    def create_session(
        self,
        agent_id: str,
        *,
        status: SessionStatus | str = SessionStatus.idle,
    ) -> SessionRecord:
        with self._session_factory() as session:
            row = SessionORM(id=str(uuid4()), agent_id=agent_id, status=status)
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._to_session_record(row)

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._session_factory() as session:
            row = session.get(SessionORM, session_id)
            if row is None:
                return None
            return self._to_session_record(row)

    def list_sessions(self, agent_id: str) -> list[SessionRecord]:
        with self._session_factory() as session:
            rows = (
                session.query(SessionORM)
                .filter(SessionORM.agent_id == agent_id)
                .order_by(SessionORM.created_at.asc())
                .all()
            )
            return [self._to_session_record(row) for row in rows]

    def upsert_session(
        self,
        session_id: str,
        agent_id: str,
        status: str,
        context_initialized: bool = False,
        runtime_type: str | None = None,
        created_at: datetime | None = None,
        remote_runtime_agent_id: str | None = None,
    ) -> SessionRecord:
        """Upsert session from witty-agent-server"""
        with self._session_factory() as session:
            existing = session.get(SessionORM, session_id)
            now = datetime.now(timezone.utc)

            if existing is None:
                row = SessionORM(
                    id=session_id,
                    agent_id=agent_id,
                    remote_runtime_agent_id=remote_runtime_agent_id,
                    status=SessionStatus(status),
                    created_at=created_at or now,
                    updated_at=now,
                )
                session.add(row)
            else:
                existing.status = SessionStatus(status)
                existing.remote_runtime_agent_id = (
                    remote_runtime_agent_id or existing.remote_runtime_agent_id
                )
                existing.updated_at = now

            session.commit()
            session.refresh(existing or row)
            return self._to_session_record(existing or row)

    def delete_session(self, session_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(SessionORM, session_id)
            if row is None:
                return
            session.delete(row)
            session.commit()

    def save_sandbox_state(
        self,
        agent_id: str,
        sandbox_payload_json: dict[str, Any],
        adapter_base_url: str | None,
        adapter_ready: bool = False,
        last_error: str | None = None,
    ) -> SandboxStateRecord:
        with self._session_factory() as session:
            row = session.get(AgentRuntimeStateORM, agent_id)
            if row is None:
                row = AgentRuntimeStateORM(agent_id=agent_id)
                session.add(row)
            row.runtime_payload_json = dict(sandbox_payload_json)
            row.adapter_base_url = adapter_base_url
            row.adapter_ready = adapter_ready
            row.last_error = last_error
            session.commit()
            session.refresh(row)
            return self._to_sandbox_state_record(row)

    def get_sandbox_state(self, agent_id: str) -> SandboxStateRecord | None:
        with self._session_factory() as session:
            row = session.get(AgentRuntimeStateORM, agent_id)
            if row is None:
                return None
            return self._to_sandbox_state_record(row)

    def create_message(
        self,
        agent_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata_json: dict[str, Any] | None = None,
    ) -> str:
        with self._session_factory() as session:
            row = MessageORM(
                id=str(uuid4()),
                agent_id=agent_id,
                session_id=session_id,
                role=role,
                content=content,
                metadata_json=dict(metadata_json or {}),
            )
            session.add(row)
            session.commit()
            return row.id

    def create_message_event_with_retry(
        self,
        *,
        agent_id: str,
        session_id: str,
        event_type: str,
        payload_json: dict[str, Any],
        seq_no: int,
        message_id: str | None = None,
        max_retries: int = 5,
    ) -> tuple[str, int]:
        next_seq_no = seq_no
        last_error: IntegrityError | None = None

        for _ in range(max_retries):
            try:
                event_id = self._create_message_event_once(
                    agent_id=agent_id,
                    session_id=session_id,
                    event_type=event_type,
                    payload_json=payload_json,
                    seq_no=next_seq_no,
                    message_id=message_id,
                )
                return event_id, next_seq_no
            except IntegrityError as exc:
                if not self._is_message_event_seq_conflict(exc):
                    raise
                last_error = exc
                next_seq_no = self._get_next_message_event_seq(session_id=session_id)

        if last_error is not None:
            raise last_error
        raise RuntimeError("Failed to create message event with retry.")

    def create_assistant_message_and_bind_events(
        self,
        *,
        agent_id: str,
        session_id: str,
        content: str,
        event_ids: list[str],
        metadata_json: dict[str, Any] | None = None,
    ) -> str:
        with self._session_factory() as session:
            row = MessageORM(
                id=str(uuid4()),
                agent_id=agent_id,
                session_id=session_id,
                role="assistant",
                content=content,
                metadata_json=dict(metadata_json or {}),
            )
            session.add(row)
            session.flush()
            if event_ids:
                session.query(MessageEventORM).filter(
                    MessageEventORM.id.in_(event_ids)
                ).update(
                    {MessageEventORM.message_id: row.id},
                    synchronize_session=False,
                )
            session.commit()
            return row.id

    def _get_next_message_event_seq(self, *, session_id: str) -> int:
        with self._session_factory() as session:
            max_seq_no = (
                session.query(func.max(MessageEventORM.seq_no))
                .filter(MessageEventORM.session_id == session_id)
                .scalar()
            )
            return int(max_seq_no or 0) + 1

    def _create_message_event_once(
        self,
        *,
        agent_id: str,
        session_id: str,
        event_type: str,
        payload_json: dict[str, Any],
        seq_no: int,
        message_id: str | None = None,
    ) -> str:
        with self._session_factory() as session:
            row = MessageEventORM(
                id=str(uuid4()),
                agent_id=agent_id,
                session_id=session_id,
                message_id=message_id,
                event_type=event_type,
                payload_json=dict(payload_json),
                seq_no=seq_no,
            )
            session.add(row)
            session.commit()
            return row.id

    @staticmethod
    def _is_message_event_seq_conflict(exc: IntegrityError) -> bool:
        message = str(exc.orig if exc.orig is not None else exc)
        return (
            "uq_message_events_session_seq" in message
            or "message_events.session_id, message_events.seq_no" in message
        )

    def delete_agent(self, agent_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(AgentORM, agent_id)
            if row is None:
                return
            builtin_skill_ids = [
                skill_id
                for (skill_id,) in (
                    session.query(AgentSkillORM.skill_id)
                    .filter(
                        AgentSkillORM.agent_id == agent_id,
                        AgentSkillORM.source_type == 'builtin',
                    )
                    .all()
                )
            ]
            session.delete(row)
            session.flush()
            for skill_id in builtin_skill_ids:
                skill_row = session.get(SkillORM, skill_id)
                if skill_row is not None:
                    session.delete(skill_row)
            session.commit()

    @staticmethod
    def _serialize_status(status: AgentStatus | str) -> str:
        return (
            status.value
            if isinstance(status, AgentStatus)
            else AgentStatus(status).value
        )

    @staticmethod
    def _to_agent_record(row: AgentORM) -> AgentRecord:
        return AgentRecord(
            id=row.id,
            name=row.name,
            description=row.description,
            sandbox_type=row.sandbox_type,
            adapter_type=row.adapter_type,
            status=AgentStatus(row.status),
            sandbox_id=row.sandbox_id,
            workspace_path=row.workspace_path,
            idle_timeout_seconds=row.idle_timeout_seconds,
            has_scheduled_tasks=row.has_scheduled_tasks,
            last_active_at=row.last_active_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _to_session_record(row: SessionORM) -> SessionRecord:
        return SessionRecord(
            id=row.id,
            agent_id=row.agent_id,
            remote_runtime_agent_id=row.remote_runtime_agent_id,
            status=row.status.value
            if isinstance(row.status, SessionStatus)
            else row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _to_sandbox_state_record(row: AgentRuntimeStateORM) -> SandboxStateRecord:
        return SandboxStateRecord(
            agent_id=row.agent_id,
            sandbox_payload_json=dict(row.runtime_payload_json or {}),
            adapter_base_url=row.adapter_base_url,
            adapter_ready=row.adapter_ready,
            last_error=row.last_error,
        )

    def create_model(
        self,
        *,
        name: str,
        provider: str,
        api_key: str,
        api_base_url: str | None = None,
        description: str = "",
        enabled: bool = True,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        is_default: bool = False,
    ) -> ModelRecord:
        return self.create_model_with_id(
            model_id=str(uuid4()),
            name=name,
            provider=provider,
            api_key=api_key,
            api_base_url=api_base_url,
            description=description,
            enabled=enabled,
            max_tokens=max_tokens,
            temperature=temperature,
            is_default=is_default,
        )

    def create_model_with_id(
        self,
        *,
        model_id: str,
        name: str,
        provider: str,
        api_key: str,
        api_base_url: str | None = None,
        description: str = "",
        enabled: bool = True,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        is_default: bool = False,
    ) -> ModelRecord:
        with self._session_factory() as session:
            row = ModelORM(
                id=model_id,
                name=name,
                provider=provider,
                api_key=api_key,
                api_base_url=api_base_url,
                description=description,
                enabled=enabled,
                max_tokens=max_tokens,
                temperature=temperature,
                is_default=is_default,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._to_model_record(row)

    def list_models(self) -> list[ModelRecord]:
        with self._session_factory() as session:
            rows = session.query(ModelORM).order_by(ModelORM.created_at.asc()).all()
            return [self._to_model_record(row) for row in rows]

    def get_model(self, model_id: str) -> ModelRecord | None:
        with self._session_factory() as session:
            row = session.get(ModelORM, model_id)
            if row is None:
                return None
            return self._to_model_record(row)

    def delete_model(self, model_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(ModelORM, model_id)
            if row is None:
                return
            session.delete(row)
            session.commit()

    @staticmethod
    def _to_model_record(row: ModelORM) -> ModelRecord:
        return ModelRecord(
            id=row.id,
            name=row.name,
            provider=row.provider,
            api_key=row.api_key,
            api_base_url=row.api_base_url,
            description=row.description,
            enabled=row.enabled,
            max_tokens=row.max_tokens,
            temperature=row.temperature,
            is_default=row.is_default,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def list_skill_repositories(self) -> list[SkillRepositoryRecord]:
        with self._session_factory() as session:
            rows = (
                session.query(SkillRepositoryORM)
                .order_by(
                    SkillRepositoryORM.created_at.desc(),
                    SkillRepositoryORM.repo_name.asc(),
                )
                .all()
            )
            return [self._to_skill_repository_record(row) for row in rows]

    def get_skill_repository(self, repo_id: str) -> SkillRepositoryRecord | None:
        with self._session_factory() as session:
            row = session.get(SkillRepositoryORM, repo_id)
            if row is None:
                return None
            return self._to_skill_repository_record(row)

    def get_skill_repository_by_name(self, name: str) -> SkillRepositoryRecord | None:
        with self._session_factory() as session:
            row = (
                session.query(SkillRepositoryORM)
                .filter(SkillRepositoryORM.repo_name == name)
                .one_or_none()
            )
            if row is None:
                return None
            return self._to_skill_repository_record(row)

    def create_skill_repository(
        self,
        *,
        name: str,
        source_type: str,
        branch: str | None,
        url: str | None,
        local_path: str | None,
        skill_discover_status: str | None,
    ) -> SkillRepositoryRecord:
        with self._session_factory() as session:
            row = SkillRepositoryORM(
                repo_id=str(uuid4()),
                repo_name=name,
                source_type=source_type,
                branch=branch,
                url=url,
                local_path=local_path,
                skill_discover_status=skill_discover_status,
                skill_num=0,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._to_skill_repository_record(row)

    def update_skill_repository(
        self,
        repo_id: str,
        **updates: Any,
    ) -> SkillRepositoryRecord:
        with self._session_factory() as session:
            row = session.get(SkillRepositoryORM, repo_id)
            if row is None:
                raise KeyError(f'Skill repository not found: {repo_id}')
            for key, value in updates.items():
                setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(row)
            return self._to_skill_repository_record(row)

    def delete_skill_repository(self, repo_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(SkillRepositoryORM, repo_id)
            if row is None:
                return
            session.delete(row)
            session.commit()

    def get_skills_by_repo_id(self, repo_id: str) -> list[SkillRecord]:
        with self._session_factory() as session:
            rows = (
                session.query(SkillORM)
                .filter(SkillORM.repo_id == repo_id)
                .order_by(SkillORM.created_at.asc(), SkillORM.skill_name.asc())
                .all()
            )
            return [self._to_skill_record(row) for row in rows]

    def get_skill_by_skill_id(self, skill_id: str) -> SkillRecord | None:
        with self._session_factory() as session:
            row = (
                session.query(SkillORM)
                .filter(SkillORM.skill_id == skill_id)
                .one_or_none()
            )
            if row is None:
                return None
            return self._to_skill_record(row)

    def list_skills(self) -> list[SkillRecord]:
        with self._session_factory() as session:
            rows = (
                session.query(SkillORM)
                .order_by(SkillORM.created_at.asc(), SkillORM.skill_name.asc())
                .all()
            )
            return [self._to_skill_record(row) for row in rows]

    def update_skills(
        self,
        repo_id: str,
        skills: list[SkillRecord],
    ) -> None:
        with self._session_factory() as session:
            repository = session.get(SkillRepositoryORM, repo_id)
            if repository is None:
                raise KeyError(f'Skill repository not found: {repo_id}')

            session.query(SkillORM).filter(SkillORM.repo_id == repo_id).delete(
                synchronize_session=False
            )

            for item in skills:
                skill_id = item.skill_id or str(uuid4())
                row = SkillORM(
                    skill_id=skill_id,
                    repo_id=repo_id,
                    skill_name=item.skill_name or '',
                    relative_path=item.relative_path,
                    metadata_json=dict(item.metadata or {}),
                    skill_source=item.skill_source,
                    skill_md_url=item.skill_md_url,
                )
                session.add(row)

            session.commit()

    def upsert_builtin_skill(
        self,
        *,
        skill_id: str,
        skill_name: str,
        metadata: dict[str, Any],
        skill_source: str | None = None,
        relative_path: str | None = None,
    ) -> SkillRecord:
        with self._session_factory() as session:
            row = session.get(SkillORM, skill_id)
            if row is None:
                row = SkillORM(
                    skill_id=skill_id,
                    repo_id=None,
                    skill_name=skill_name,
                    relative_path=relative_path,
                    metadata_json=dict(metadata),
                    skill_source=skill_source,
                    skill_md_url=None,
                )
                session.add(row)
            else:
                row.repo_id = None
                row.skill_name = skill_name
                row.relative_path = relative_path
                row.metadata_json = dict(metadata)
                row.skill_source = skill_source
                row.skill_md_url = None
            session.commit()
            session.refresh(row)
            return self._to_skill_record(row)

    def upsert_installed_agent_skill(
        self,
        *,
        agent_id: str,
        skill_id: str,
        source_type: str,
        skill_name: str,
        repo_id: str | None = None,
        installed_at: datetime | None = None,
    ) -> AgentSkillRecord:
        with self._session_factory() as session:
            row = session.get(AgentSkillORM, (agent_id, skill_id))
            timestamp = installed_at or datetime.now(timezone.utc)
            if row is None:
                row = AgentSkillORM(
                    agent_id=agent_id,
                    skill_id=skill_id,
                    source_type=source_type,
                    repo_id=repo_id,
                    skill_name=skill_name,
                    installed_at=timestamp,
                )
                session.add(row)
            else:
                row.source_type = source_type
                row.repo_id = repo_id
                row.skill_name = skill_name
                row.installed_at = timestamp
            session.commit()
            session.refresh(row)
            return self._to_agent_skill_record(row)

    def replace_installed_agent_skills_from_runtime(
        self,
        *,
        agent_id: str,
        skills: list[dict[str, Any]],
    ) -> None:
        """Replace one agent's installed skills from runtime snapshot in a single transaction."""
        with self._session_factory() as session:
            timestamp = datetime.now(timezone.utc)
            normalized_skills: list[dict[str, Any]] = []
            seen_names: set[str] = set()
            for item in skills:
                if not isinstance(item, dict):
                    continue
                raw_name = item.get("name")
                if not isinstance(raw_name, str):
                    continue
                skill_name = raw_name.strip()
                if not skill_name or skill_name in seen_names:
                    continue
                seen_names.add(skill_name)
                normalized_skills.append(
                    {
                        "skill_id": str(uuid5(NAMESPACE_URL, f"builtin:{agent_id}:{skill_name}")),
                        "skill_name": skill_name,
                        "metadata": dict(item),
                        "skill_source": item.get("source")
                        if isinstance(item.get("source"), str)
                        else None,
                        "relative_path": item.get("filePath")
                        if isinstance(item.get("filePath"), str)
                        else None,
                    }
                )

            previous_builtin_skill_ids = [
                skill_id
                for (skill_id,) in (
                    session.query(AgentSkillORM.skill_id)
                    .filter(
                        AgentSkillORM.agent_id == agent_id,
                        AgentSkillORM.source_type == 'builtin',
                    )
                    .all()
                )
            ]

            session.query(AgentSkillORM).filter(AgentSkillORM.agent_id == agent_id).delete(
                synchronize_session=False
            )

            next_builtin_skill_ids = {item["skill_id"] for item in normalized_skills}
            obsolete_builtin_ids = [
                skill_id
                for skill_id in previous_builtin_skill_ids
                if skill_id not in next_builtin_skill_ids
            ]
            if obsolete_builtin_ids:
                session.query(SkillORM).filter(SkillORM.skill_id.in_(obsolete_builtin_ids)).delete(
                    synchronize_session=False
                )

            for item in normalized_skills:
                skill_row = session.get(SkillORM, item["skill_id"])
                if skill_row is None:
                    skill_row = SkillORM(
                        skill_id=item["skill_id"],
                        repo_id=None,
                        skill_name=item["skill_name"],
                        relative_path=item["relative_path"],
                        metadata_json=item["metadata"],
                        skill_source=item["skill_source"],
                        skill_md_url=None,
                    )
                    session.add(skill_row)
                else:
                    skill_row.repo_id = None
                    skill_row.skill_name = item["skill_name"]
                    skill_row.relative_path = item["relative_path"]
                    skill_row.metadata_json = item["metadata"]
                    skill_row.skill_source = item["skill_source"]
                    skill_row.skill_md_url = None
                    skill_row.updated_at = timestamp

                session.add(
                    AgentSkillORM(
                        agent_id=agent_id,
                        skill_id=item["skill_id"],
                        source_type='builtin',
                        repo_id=None,
                        skill_name=item["skill_name"],
                        installed_at=timestamp,
                    )
                )

            session.commit()

    def list_installed_agent_skills(self, agent_id: str) -> list[AgentSkillRecord]:
        with self._session_factory() as session:
            rows = (
                session.query(AgentSkillORM, SkillORM)
                .outerjoin(SkillORM, AgentSkillORM.skill_id == SkillORM.skill_id)
                .filter(AgentSkillORM.agent_id == agent_id)
                .order_by(AgentSkillORM.installed_at.asc(), AgentSkillORM.skill_name.asc())
                .all()
            )
            return [
                self._to_agent_skill_record(agent_skill_row, skill_row)
                for agent_skill_row, skill_row in rows
            ]

    def get_installed_agent_skill(
        self,
        *,
        agent_id: str,
        skill_id: str,
    ) -> AgentSkillRecord | None:
        with self._session_factory() as session:
            row = (
                session.query(AgentSkillORM, SkillORM)
                .outerjoin(SkillORM, AgentSkillORM.skill_id == SkillORM.skill_id)
                .filter(
                    AgentSkillORM.agent_id == agent_id,
                    AgentSkillORM.skill_id == skill_id,
                )
                .one_or_none()
            )
            if row is None:
                return None
            agent_skill_row, skill_row = row
            return self._to_agent_skill_record(agent_skill_row, skill_row)

    def delete_installed_agent_skill(self, *, agent_id: str, skill_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(AgentSkillORM, (agent_id, skill_id))
            is_builtin_skill = row is not None and row.source_type == 'builtin'
            if row is None:
                return
            session.delete(row)
            session.flush()
            if is_builtin_skill:
                # 只有builtin的skill，需要同 skills 表里的那条 builtin skill 元数据一起清理
                skill_row = session.get(SkillORM, skill_id)
                if skill_row is not None:
                    session.delete(skill_row)
            session.commit()

    @staticmethod
    def _to_skill_repository_record(row: SkillRepositoryORM) -> SkillRepositoryRecord:
        return SkillRepositoryRecord(
            repo_id=row.repo_id,
            repo_name=row.repo_name,
            source_type=row.source_type,
            branch=row.branch,
            url=row.url,
            local_path=row.local_path,
            skill_discover_status=row.skill_discover_status,
            skill_num=row.skill_num,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _to_skill_record(row: SkillORM) -> SkillRecord:
        return SkillRecord(
            skill_id=row.skill_id,
            repo_id=row.repo_id,
            skill_name=row.skill_name,
            relative_path=row.relative_path,
            metadata=dict(row.metadata_json or {}),
            skill_source=row.skill_source,
            skill_md_url=row.skill_md_url,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _to_agent_skill_record(
        row: AgentSkillORM,
        skill_row: SkillORM | None = None,
    ) -> AgentSkillRecord:
        return AgentSkillRecord(
            agent_id=row.agent_id,
            skill_id=row.skill_id,
            source_type=row.source_type,
            repo_id=row.repo_id,
            skill_name=row.skill_name,
            installed_at=row.installed_at,
            relative_path=skill_row.relative_path if skill_row is not None else None,
            metadata=dict(skill_row.metadata_json or {}) if skill_row is not None else None,
            skill_source=skill_row.skill_source if skill_row is not None else None,
            skill_md_url=skill_row.skill_md_url if skill_row is not None else None,
        )
