import logging
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from witty_service.api.agents import router as agents_router
from witty_service.api.cve import router as cve_router
from witty_service.api.backport import router as backport_router
from witty_service.api.errors import register_exception_handlers
from witty_service.api.models import router as models_router
from witty_service.api.services import ServiceContainer, build_default_services
from witty_service.api.skills import router as skills_router
from witty_service.application.skill_manager import SkillManager
from witty_service.config import get_settings
from witty_agent_server.api.routers.agent_router import create_agent_router
from witty_agent_server.api.routers.session_router import (
    build_default_session_service,
    create_session_router,
)
from witty_agent_server.api.routers.session_ws_router import create_session_ws_router
from witty_agent_server.application.services.agent import AgentService
from witty_agent_server.application.services.session_state_sync_service import (
    SessionStateSyncService,
)
from witty_agent_server.application.services.session_ws_orchestrator import (
    SessionWSOrchestrator,
)
from witty_agent_server.application.services.task_pool import TaskPool
from witty_agent_server.logger.logging_config import configure_logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def create_app(*, services: ServiceContainer | None = None) -> FastAPI:
    configure_logging()
    app = FastAPI(title="Witty Service")
    app.state.services = services or build_default_services()
    register_exception_handlers(app)

    agent_service = AgentService()
    session_service = build_default_session_service()
    session_state_sync_service = SessionStateSyncService()
    session_ws_orchestrator = SessionWSOrchestrator(
        session_service=session_service,
        agent_service=agent_service,
        state_sync_service=session_state_sync_service,
    )
    task_pool = TaskPool(orchestrator=session_ws_orchestrator)

    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_credentials,
        allow_methods=settings.cors_methods,
        allow_headers=settings.cors_headers,
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/server/capabilities")
    def capabilities() -> dict[str, list[str]]:
        return {"supported_runtimes": ["openclaw"]}

    @app.on_event("startup")
    def sync_awesome_openclaw_skills_on_startup() -> None:
        threading.Thread(
            target=SkillManager.sync_awesome_repository_in_background,
            kwargs={"repository": app.state.services.repository},
            daemon=True,
        ).start()

    @app.on_event("startup")
    def recover_stale_generations() -> None:
        from witty_service.persistence.orm import MessageStatus
        repository = app.state.services.repository
        stale = repository.find_stale_generating_messages(stale_threshold_seconds=30)
        for msg in stale:
            try:
                repository.update_message_status(msg.id, MessageStatus.interrupted)
                logger.info("Recovered stale generating message: %s", msg.id)
            except Exception:
                logger.warning(
                    "Failed to recover stale message: %s", msg.id, exc_info=True
                )

    app.include_router(agents_router)
    app.include_router(cve_router)
    app.include_router(models_router)
    app.include_router(skills_router)
    app.include_router(backport_router)

    app.include_router(create_agent_router(agent_service))
    app.include_router(
        create_session_router(
            session_service,
            state_sync_service=session_state_sync_service,
            agent_service=agent_service,
        )
    )
    app.include_router(
        create_session_ws_router(
            task_pool=task_pool,
            state_sync_service=session_state_sync_service,
        )
    )

    return app
