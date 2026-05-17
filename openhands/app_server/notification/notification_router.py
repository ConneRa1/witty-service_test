"""Notification router for OpenHands App Server."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from openhands.app_server.notification.notification_models import (
    CreateNotificationRequest,
    Notification,
    NotificationPage,
    NotificationPreferences,
    NotificationSettings,
    NotificationStatus,
    NotificationType,
    UpdateNotificationRequest,
)
from openhands.app_server.notification.notification_service import (
    InMemoryNotificationService,
    NotificationService,
)
from openhands.app_server.user.auth_user_context import UserContext, depends_user_context

router = APIRouter(prefix='/api/v1/notifications', tags=['Notifications'])

notification_service = InMemoryNotificationService()


@router.post('', response_model=Notification)
async def create_notification(
    request: CreateNotificationRequest,
    user_context: UserContext = depends_user_context(),
) -> Notification:
    return await notification_service.create_notification(
        user_id=user_context.user_id, request=request
    )


@router.get('', response_model=NotificationPage)
async def list_notifications(
    status: Annotated[
        NotificationStatus | None, Query(title='Filter by notification status')
    ] = None,
    notification_type: Annotated[
        NotificationType | None, Query(title='Filter by notification type')
    ] = None,
    limit: Annotated[int, Query(gt=0, le=100, title='Max results per page')] = 50,
    page_id: Annotated[str | None, Query(title='Next page ID')] = None,
    user_context: UserContext = depends_user_context(),
) -> NotificationPage:
    return await notification_service.list_notifications(
        user_id=user_context.user_id,
        status=status,
        notification_type=notification_type,
        limit=limit,
        page_id=page_id,
    )


@router.get('/unread-count')
async def get_unread_count(
    user_context: UserContext = depends_user_context(),
) -> dict:
    count = await notification_service.get_unread_count(user_context.user_id)
    return {'unread_count': count}


@router.get('/preferences', response_model=NotificationPreferences)
async def get_notification_preferences(
    user_context: UserContext = depends_user_context(),
) -> NotificationPreferences:
    preferences = await notification_service.get_notification_preferences(
        user_context.user_id
    )
    if not preferences:
        return NotificationPreferences(user_id=user_context.user_id)
    return preferences


@router.put('/preferences', response_model=NotificationPreferences)
async def update_notification_preferences(
    settings: NotificationSettings,
    user_context: UserContext = depends_user_context(),
) -> NotificationPreferences:
    return await notification_service.update_notification_preferences(
        user_id=user_context.user_id, settings=settings
    )


@router.get('/{notification_id}', response_model=Notification | None)
async def get_notification(
    notification_id: UUID,
    user_context: UserContext = depends_user_context(),
) -> Notification | None:
    return await notification_service.get_notification(
        user_id=user_context.user_id, notification_id=notification_id
    )


@router.patch('/{notification_id}', response_model=Notification | None)
async def update_notification(
    notification_id: UUID,
    request: UpdateNotificationRequest,
    user_context: UserContext = depends_user_context(),
) -> Notification | None:
    return await notification_service.update_notification(
        user_id=user_context.user_id, notification_id=notification_id, request=request
    )


@router.delete('/{notification_id}')
async def delete_notification(
    notification_id: UUID,
    user_context: UserContext = depends_user_context(),
) -> dict:
    deleted = await notification_service.delete_notification(
        user_id=user_context.user_id, notification_id=notification_id
    )
    return {'deleted': deleted}


@router.post('/mark-all-read')
async def mark_all_as_read(
    user_context: UserContext = depends_user_context(),
) -> dict:
    count = await notification_service.mark_all_as_read(user_context.user_id)
    return {'marked_count': count}


@router.post('/{notification_id}/mark-read', response_model=Notification | None)
async def mark_as_read(
    notification_id: UUID,
    user_context: UserContext = depends_user_context(),
) -> Notification | None:
    return await notification_service.update_notification(
        user_id=user_context.user_id,
        notification_id=notification_id,
        request=UpdateNotificationRequest(status=NotificationStatus.READ),
    )