from fastapi import APIRouter, Depends, Query, Request

from witty_service.api.auth import require_bearer_auth
from witty_service.api.backport_schemas import (
    BackportConfigPayload,
    BackportConfigUpdateResponse,
    BackportRunRequest,
    BackportRunResponse,
)
from witty_service.api.services import ServiceContainer
from witty_service.application.backport_service import BackportService

router = APIRouter(
    prefix="/backport",
    tags=["backport"],
    dependencies=[Depends(require_bearer_auth)],
)


def get_services(request: Request) -> ServiceContainer:
    return request.app.state.services


def get_backport_service(
    services: ServiceContainer = Depends(get_services),
) -> BackportService:
    return BackportService(services)


@router.get("/config", response_model=BackportConfigPayload)
def get_config(
    backport_service: BackportService = Depends(get_backport_service),
) -> BackportConfigPayload:
    return BackportConfigPayload(**backport_service.get_config())


@router.put("/config", response_model=BackportConfigUpdateResponse)
def update_config(
    payload: BackportConfigPayload,
    backport_service: BackportService = Depends(get_backport_service),
) -> BackportConfigUpdateResponse:
    backport_service.update_config(payload.model_dump())
    return BackportConfigUpdateResponse(ok=True, config_path=backport_service.config_path)


@router.get("/browse")
def browse_path(
    path: str | None = Query(default=None),
    backport_service: BackportService = Depends(get_backport_service),
) -> dict:
    return backport_service.browse_path(path)


@router.post("/run", response_model=BackportRunResponse)
def run_action(
    payload: BackportRunRequest,
    backport_service: BackportService = Depends(get_backport_service),
) -> BackportRunResponse:
    return BackportRunResponse(**backport_service.run_action(payload.action, payload.payload))
