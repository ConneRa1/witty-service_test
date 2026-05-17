from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import Field

from openhands.agent_server.utils import OpenHandsUUID, utc_now
from openhands.sdk.utils.models import OpenHandsModel


class NotificationType(str, Enum):
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_STARTED = "TASK_STARTED"
    LONG_RUNNING_WARNING = "LONG_RUNNING_WARNING"
    SECURITY_ALERT = "SECURITY_ALERT"
    SYSTEM_MESSAGE = "SYSTEM_MESSAGE"
    USER_MESSAGE = "USER_MESSAGE"
    CONVERSATION_SHARED = "CONVERSATION_SHARED"
    MENTION = "MENTION"


class NotificationPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class NotificationStatus(str, Enum):
    UNREAD = "UNREAD"
    READ = "READ"
    ARCHIVED = "ARCHIVED"


class Notification(OpenHandsModel):
    id: OpenHandsUUID = Field(default_factory=uuid4)
    user_id: UUID
    title: str = Field(..., max_length=255)
    message: str = Field(..., max_length=2000)
    notification_type: NotificationType
    priority: NotificationPriority = Field(default=NotificationPriority.NORMAL)
    status: NotificationStatus = Field(default=NotificationStatus.UNREAD)
    conversation_id: UUID | None = None
    task_id: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    read_at: datetime | None = None


class NotificationPage(OpenHandsModel):
    items: list[Notification]
    next_page_id: str | None = None
    total_count: int = 0


class CreateNotificationRequest(OpenHandsModel):
    title: str = Field(..., max_length=255)
    message: str = Field(..., max_length=2000)
    notification_type: NotificationType
    priority: NotificationPriority = Field(default=NotificationPriority.NORMAL)
    conversation_id: UUID | None = None
    task_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class UpdateNotificationRequest(OpenHandsModel):
    status: NotificationStatus | None = None
    metadata: dict | None = None


class NotificationSettings(OpenHandsModel):
    email_enabled: bool = Field(default=False)
    slack_enabled: bool = Field(default=False)
    web_push_enabled: bool = Field(default=True)
    notification_types: dict[NotificationType, bool] = Field(default_factory=dict)
    quiet_hours_start: str | None = Field(default=None, description="HH:MM format")
    quiet_hours_end: str | None = Field(default=None, description="HH:MM format")
    timezone: str = Field(default="UTC")


class NotificationPreferences(OpenHandsModel):
    user_id: UUID
    settings: NotificationSettings = Field(default_factory=NotificationSettings)
    enabled: bool = Field(default=True)
    updated_at: datetime = Field(default_factory=utc_now)
