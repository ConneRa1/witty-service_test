from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

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

if TYPE_CHECKING:
    from openhands.app_server.services.injector import Injector

logger = logging.getLogger(__name__)


class NotificationService(ABC):
    @abstractmethod
    async def create_notification(
        self, user_id: UUID, request: CreateNotificationRequest
    ) -> Notification:
        pass

    @abstractmethod
    async def get_notification(
        self, user_id: UUID, notification_id: UUID
    ) -> Notification | None:
        pass

    @abstractmethod
    async def list_notifications(
        self,
        user_id: UUID,
        status: NotificationStatus | None = None,
        notification_type: NotificationType | None = None,
        limit: int = 50,
        page_id: str | None = None,
    ) -> NotificationPage:
        pass

    @abstractmethod
    async def update_notification(
        self, user_id: UUID, notification_id: UUID, request: UpdateNotificationRequest
    ) -> Notification | None:
        pass

    @abstractmethod
    async def delete_notification(
        self, user_id: UUID, notification_id: UUID
    ) -> bool:
        pass

    @abstractmethod
    async def mark_all_as_read(self, user_id: UUID) -> int:
        pass

    @abstractmethod
    async def get_unread_count(self, user_id: UUID) -> int:
        pass

    @abstractmethod
    async def get_notification_preferences(
        self, user_id: UUID
    ) -> NotificationPreferences | None:
        pass

    @abstractmethod
    async def update_notification_preferences(
        self, user_id: UUID, settings: NotificationSettings
    ) -> NotificationPreferences:
        pass


class NotificationServiceInjector(ABC):
    @abstractmethod
    def get_notification_service(self) -> NotificationService:
        pass


class InMemoryNotificationService(NotificationService):
    def __init__(self):
        self._notifications: dict[UUID, list[Notification]] = {}
        self._preferences: dict[UUID, NotificationPreferences] = {}

    async def create_notification(
        self, user_id: UUID, request: CreateNotificationRequest
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            title=request.title,
            message=request.message,
            notification_type=request.notification_type,
            priority=request.priority,
            conversation_id=request.conversation_id,
            task_id=request.task_id,
            metadata=request.metadata,
        )

        if user_id not in self._notifications:
            self._notifications[user_id] = []
        self._notifications[user_id].insert(0, notification)
        logger.info(f"Created notification {notification.id} for user {user_id}")
        return notification

    async def get_notification(
        self, user_id: UUID, notification_id: UUID
    ) -> Notification | None:
        notifications = self._notifications.get(user_id, [])
        for notification in notifications:
            if notification.id == notification_id:
                return notification
        return None

    async def list_notifications(
        self,
        user_id: UUID,
        status: NotificationStatus | None = None,
        notification_type: NotificationType | None = None,
        limit: int = 50,
        page_id: str | None = None,
    ) -> NotificationPage:
        notifications = self._notifications.get(user_id, [])

        if status:
            notifications = [n for n in notifications if n.status == status]
        if notification_type:
            notifications = [
                n for n in notifications if n.notification_type == notification_type
            ]

        total_count = len(notifications)
        start_idx = int(page_id) if page_id else 0
        end_idx = start_idx + limit
        page_notifications = notifications[start_idx:end_idx]

        next_page_id = str(end_idx) if end_idx < total_count else None

        return NotificationPage(
            items=page_notifications,
            next_page_id=next_page_id,
            total_count=total_count,
        )

    async def update_notification(
        self, user_id: UUID, notification_id: UUID, request: UpdateNotificationRequest
    ) -> Notification | None:
        notification = await self.get_notification(user_id, notification_id)
        if not notification:
            return None

        if request.status is not None:
            notification.status = request.status
            if request.status == NotificationStatus.READ:
                notification.read_at = datetime.utcnow()

        if request.metadata is not None:
            notification.metadata.update(request.metadata)

        return notification

    async def delete_notification(
        self, user_id: UUID, notification_id: UUID
    ) -> bool:
        notifications = self._notifications.get(user_id, [])
        for i, notification in enumerate(notifications):
            if notification.id == notification_id:
                notifications.pop(i)
                return True
        return False

    async def mark_all_as_read(self, user_id: UUID) -> int:
        notifications = self._notifications.get(user_id, [])
        count = 0
        for notification in notifications:
            if notification.status == NotificationStatus.UNREAD:
                notification.status = NotificationStatus.READ
                notification.read_at = datetime.utcnow()
                count += 1
        return count

    async def get_unread_count(self, user_id: UUID) -> int:
        notifications = self._notifications.get(user_id, [])
        return sum(1 for n in notifications if n.status == NotificationStatus.UNREAD)

    async def get_notification_preferences(
        self, user_id: UUID
    ) -> NotificationPreferences | None:
        return self._preferences.get(user_id)

    async def update_notification_preferences(
        self, user_id: UUID, settings: NotificationSettings
    ) -> NotificationPreferences:
        preferences = self._preferences.get(
            user_id,
            NotificationPreferences(user_id=user_id, settings=settings),
        )
        preferences.settings = settings
        preferences.updated_at = datetime.utcnow()
        self._preferences[user_id] = preferences
        return preferences