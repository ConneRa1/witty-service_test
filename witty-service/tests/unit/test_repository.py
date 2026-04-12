from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError, StatementError

from witty_service.domain.enums import AgentStatus
from witty_service.persistence.db import create_session_factory, create_sqlite_engine, init_db
from witty_service.persistence.orm import MessageORM
from witty_service.persistence.repositories import SqliteRepository


def build_repository(db_path: Path) -> SqliteRepository:
    engine = create_sqlite_engine(f"sqlite:///{db_path}")
    init_db(engine)
    return SqliteRepository(create_session_factory(engine))


def test_create_agent_and_session_roundtrip(tmp_path):
    repository = build_repository(tmp_path / "repository.sqlite3")

    created_agent = repository.create_agent(
        name="agent-1",
        runtime_type="local_process",
        adapter_type="http",
        workspace_path="/tmp/agent-1",
        idle_timeout_seconds=300,
        status=AgentStatus.creating,
    )

    stored_agent = repository.get_agent(created_agent.id)

    assert stored_agent is not None
    assert stored_agent.id == created_agent.id
    assert stored_agent.name == "agent-1"
    assert stored_agent.runtime_type == "local_process"
    assert stored_agent.adapter_type == "http"
    assert stored_agent.workspace_path == "/tmp/agent-1"
    assert stored_agent.idle_timeout_seconds == 300
    assert stored_agent.status is AgentStatus.creating
    assert stored_agent.has_scheduled_tasks is False
    assert stored_agent.sandbox_id is None

    created_session = repository.create_session(created_agent.id)
    stored_session = repository.get_session(created_session.id)

    assert stored_session is not None
    assert stored_session.id == created_session.id
    assert stored_session.agent_id == created_agent.id
    assert stored_session.status == "active"


def test_create_session_rejects_missing_agent(tmp_path):
    repository = build_repository(tmp_path / "repository.sqlite3")

    with pytest.raises(IntegrityError):
        repository.create_session("missing-agent-id")


def test_create_session_rejects_unknown_status(tmp_path):
    repository = build_repository(tmp_path / "repository.sqlite3")
    agent = repository.create_agent(
        name="agent-1",
        runtime_type="local_process",
        adapter_type="http",
        workspace_path="/tmp/agent-1",
        idle_timeout_seconds=300,
        status=AgentStatus.creating,
    )

    with pytest.raises((LookupError, StatementError)):
        repository.create_session(agent.id, status="bad-status")


def test_runtime_state_message_and_delete_roundtrip(tmp_path):
    db_path = tmp_path / "repository.sqlite3"
    repository = build_repository(db_path)

    created_agent = repository.create_agent_with_id(
        agent_id="agent-fixed-id",
        name="agent-1",
        runtime_type="local_process",
        adapter_type="http",
        workspace_path="/tmp/agent-1",
        idle_timeout_seconds=300,
        status=AgentStatus.creating,
    )
    created_session = repository.create_session(created_agent.id)

    updated_agent = repository.update_agent_status(created_agent.id, AgentStatus.running)
    repository.save_runtime_state(
        created_agent.id,
        runtime_payload_json={
            "runtime_id": "runtime-agent-fixed-id",
            "agent_id": created_agent.id,
            "workspace_path": "/tmp/agent-1",
            "metadata": {"port": 8000},
        },
        adapter_base_url="http://adapter/runtime-agent-fixed-id",
        adapter_ready=True,
    )
    repository.create_message(
        agent_id=created_agent.id,
        session_id=created_session.id,
        role="user",
        content="hello",
        metadata_json={"source": "test"},
    )

    runtime_state = repository.get_runtime_state(created_agent.id)

    assert updated_agent.status is AgentStatus.running
    assert runtime_state is not None
    assert runtime_state.handle.runtime_id == "runtime-agent-fixed-id"
    assert runtime_state.adapter_base_url == "http://adapter/runtime-agent-fixed-id"

    engine = create_sqlite_engine(f"sqlite:///{db_path}")
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        stored_message = session.query(MessageORM).one()
        assert stored_message.content == "hello"
        assert stored_message.metadata_json == {"source": "test"}

    repository.delete_agent(created_agent.id)

    assert repository.get_agent(created_agent.id) is None
    assert repository.get_session(created_session.id) is None
    assert repository.get_runtime_state(created_agent.id) is None
