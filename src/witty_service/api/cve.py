from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from witty_service.api.auth import require_bearer_auth
from witty_service.api.cve_schemas import (
    CveArtifactResponse,
    CveConfigResponse,
    CveConfigUpdateResponse,
    CveIssueListResponse,
    CveWorkbenchResponse,
    UpdateCveConfigRequest,
)
from witty_service.api.services import ServiceContainer
from witty_service.application.cve_service import CveService

router = APIRouter(prefix="/cve", tags=["cve"], dependencies=[Depends(require_bearer_auth)])


def get_services(request: Request) -> ServiceContainer:
    return request.app.state.services


def get_cve_service(services: ServiceContainer = Depends(get_services)) -> CveService:
    return CveService(services)


@router.get("/config", response_model=CveConfigResponse)
def get_config(cve_service: CveService = Depends(get_cve_service)) -> CveConfigResponse:
    config = cve_service.get_config()
    return CveConfigResponse(
        has_gitcode_token=bool(config.get("gitcode_token", "").strip()),
        signer_name=config.get("signer_name", ""),
        signer_email=config.get("signer_email", ""),
        clone_dir=config.get("clone_dir", ""),
        branches=config.get("branches", ""),
        fork_repo_url=config.get("fork_repo_url", ""),
        repo_url=config.get("repo_url", ""),
        issue_url=config.get("issue_url", ""),
    )


@router.put("/config", response_model=CveConfigUpdateResponse)
def update_config(
    payload: UpdateCveConfigRequest,
    cve_service: CveService = Depends(get_cve_service),
) -> CveConfigUpdateResponse:
    cve_service.update_config(payload.model_dump())
    return CveConfigUpdateResponse(ok=True)


@router.put("/token", response_model=CveConfigUpdateResponse)
def update_token(
    x_gitcode_token: str | None = Header(default=None),
    cve_service: CveService = Depends(get_cve_service),
) -> CveConfigUpdateResponse:
    token = (x_gitcode_token or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitCode-Token header",
        )
    cve_service.update_token(token)
    return CveConfigUpdateResponse(ok=True)


@router.get("/workbench", response_model=CveWorkbenchResponse)
def get_workbench(
    cve_id: str = Query(min_length=1),
    branches: str = Query(default=""),
    clone_dir: str = Query(default=""),
    cve_service: CveService = Depends(get_cve_service),
) -> CveWorkbenchResponse:
    workbench = cve_service.get_workbench(
        cve_id=cve_id,
        branches=branches,
        clone_dir=clone_dir,
    )
    return CveWorkbenchResponse(**workbench)


@router.get("/artifact", response_model=CveArtifactResponse)
def get_artifact(
    path: str = Query(min_length=1),
    cve_service: CveService = Depends(get_cve_service),
) -> CveArtifactResponse:
    artifact = cve_service.read_artifact(path)
    return CveArtifactResponse(**artifact)


@router.get("/issues", response_model=CveIssueListResponse)
def get_issues(
    issue_url: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    cve_service: CveService = Depends(get_cve_service),
) -> CveIssueListResponse:
    config = cve_service.get_config()
    items = cve_service.get_issues(issue_url=issue_url, limit=limit, token=config.get("gitcode_token", ""))
    return CveIssueListResponse(items=items)


@router.get("/issues/search", response_model=CveIssueListResponse)
def search_issues(
    issue_url: str = Query(min_length=1),
    query: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    cve_service: CveService = Depends(get_cve_service),
) -> CveIssueListResponse:
    config = cve_service.get_config()
    items = cve_service.search_issues(
        issue_url=issue_url,
        query=query,
        limit=limit,
        token=config.get("gitcode_token", ""),
    )
    return CveIssueListResponse(items=items)
