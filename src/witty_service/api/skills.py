from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from witty_service.api.auth import require_bearer_auth
from witty_service.api.schemas import SkillRepositoryRequest, SkillRepositoryResponse, SkillResponse
from witty_service.api.services import ServiceContainer
from witty_service.application.skill_manager import SkillManager
from witty_service.persistence.repositories import SkillRepositoryRecord

router = APIRouter(
    prefix='/skills',
    tags=['skills'],
    dependencies=[Depends(require_bearer_auth)],
)


def get_services(request: Request) -> ServiceContainer:
    return request.app.state.services


def _build_service(services: ServiceContainer) -> SkillManager:
    return SkillManager(repository=services.repository)


@router.get('/repos', response_model=list[SkillRepositoryResponse])
def list_skill_repositories(
    services: ServiceContainer = Depends(get_services),
) -> list[SkillRepositoryResponse]:
    service = _build_service(services)
    return [
        _to_skill_repository_response(item)
        for item in service.list_skill_repositories()
    ]


@router.post(
    '/repos',
    response_model=SkillRepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_skill_repository_from_git(
    payload: SkillRepositoryRequest,
    background_tasks: BackgroundTasks,
    services: ServiceContainer = Depends(get_services),
) -> SkillRepositoryResponse:
    service = _build_service(services)
    try:
        created = service.create_skill_repository_from_git(payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    background_tasks.add_task(
        service.discover_skill_repository_in_background,
        repository=services.repository,
        repo_id=created.repo_id,
    )
    return _to_skill_repository_response(created)


@router.post(
    '/repos/upload',
    response_model=SkillRepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_skill_repository_archive(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    services: ServiceContainer = Depends(get_services),
) -> SkillRepositoryResponse:
    service = _build_service(services)
    try:
        created = service.create_skill_repository_from_archive(file)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    
    background_tasks.add_task(
        service.discover_skill_repository_in_background,    
        repository=services.repository,
        repo_id=created.repo_id,
    )
    
    return SkillRepositoryResponse(
        repo_id=created.repo_id,
        repo_name=created.repo_name,
        source_type=created.source_type,
        branch=None,
        url=None,
        local_path=created.local_path or '',
        skill_discover_status=created.skill_discover_status,
        skill_num=created.skill_num,
    )


@router.patch('/repos/{repo_id}', response_model=SkillRepositoryResponse)
def update_skill_repository(
    repo_id: str,
    payload: SkillRepositoryRequest,
    services: ServiceContainer = Depends(get_services),
) -> SkillRepositoryResponse:
    service = _build_service(services)
    try:
        updated = service.update_skill_repository(repo_id, payload)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_skill_repository_response(updated)


@router.delete('/repos/{repo_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_skill_repository(
    repo_id: str,
    services: ServiceContainer = Depends(get_services),
) -> Response:
    service = _build_service(services)
    try:
        service.delete_skill_repository(repo_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get('/repos/{repo_id}', response_model=SkillRepositoryResponse)
def get_skill_repository(
    repo_id: str,
    services: ServiceContainer = Depends(get_services),
) -> SkillRepositoryResponse:
    service = _build_service(services)
    try:
        repository = service.get_repository_by_repo_id(repo_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_skill_repository_response(repository)


@router.post('/discover', response_model=list[SkillRepositoryResponse])
def discover_skill_repositories(
    services: ServiceContainer = Depends(get_services),
) -> list[SkillRepositoryResponse]:
    service = _build_service(services)
    return [
        _to_skill_repository_response(item)
        for item in service.discover_skill_repositories()
    ]


@router.post('/discover/{repo_id}', response_model=SkillRepositoryResponse)
def discover_one_skill_repository(
    repo_id: str,
    services: ServiceContainer = Depends(get_services),
) -> SkillRepositoryResponse:
    service = _build_service(services)
    try:
        repository = service.discover_one_skill_repository(repo_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        if str(exc) == 'Skill repository discovery is already in progress':
            raise HTTPException(status.HTTP_202_ACCEPTED, detail=str(exc)) from exc
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_skill_repository_response(repository)


@router.get('/skills', response_model=list[SkillResponse])
def list_skills(
    services: ServiceContainer = Depends(get_services),
) -> list[SkillResponse]:
    service = _build_service(services)
    skills = service.list_skills()
    return [SkillResponse.model_validate(item) for item in skills]


def _to_skill_repository_response(
    item: SkillRepositoryRecord,
) -> SkillRepositoryResponse:
    return SkillRepositoryResponse.model_validate(item)
