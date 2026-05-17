import React from "react";
import { useNotifications, useUnreadNotificationCount } from "#/hooks/query/use-notifications";
import {
  useMarkNotificationAsRead,
  useMarkAllNotificationsAsRead,
} from "#/hooks/mutation/use-notification-mutations";
import type { Notification } from "#/api/notification-service/notification-service.types";
import { NotificationPriority } from "#/api/notification-service/notification-service.types";

interface NotificationItemProps {
  notification: Notification;
  onMarkAsRead: (id: string) => void;
}

const NotificationItem: React.FC<NotificationItemProps> = ({
  notification,
  onMarkAsRead,
}) => {
  const isUnread = notification.status === "UNREAD";

  const getPriorityColor = (priority: NotificationPriority) => {
    switch (priority) {
      case NotificationPriority.URGENT:
        return "text-red-500";
      case NotificationPriority.HIGH:
        return "text-orange-500";
      case NotificationPriority.NORMAL:
        return "text-blue-500";
      case NotificationPriority.LOW:
        return "text-gray-500";
      default:
        return "text-blue-500";
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString() + " " + date.toLocaleTimeString();
  };

  return (
    <div
      className={`p-4 border-b border-gray-200 hover:bg-gray-50 cursor-pointer ${
        isUnread ? "bg-blue-50" : ""
      }`}
      onClick={() => onMarkAsRead(notification.id)}
    >
      <div className="flex items-start gap-3">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className={`font-semibold ${isUnread ? "text-gray-900" : "text-gray-700"}`}>
              {notification.title}
            </span>
            <span className={`text-sm ${getPriorityColor(notification.priority)}`}>
              {notification.priority}
            </span>
          </div>
          <p className="text-sm text-gray-600 mt-1">{notification.message}</p>
          <p className="text-xs text-gray-400 mt-2">
            {formatDate(notification.created_at)}
          </p>
        </div>
        {isUnread && (
          <span className="w-2 h-2 rounded-full bg-blue-500 flex-shrink-0" />
        )}
      </div>
    </div>
  );
};

export const NotificationCenter: React.FC = () => {
  const { data: notificationsData, isLoading } = useNotifications();
  const { data: unreadData } = useUnreadNotificationCount();
  const markAsRead = useMarkNotificationAsRead();
  const markAllAsRead = useMarkAllNotificationsAsRead();

  const handleMarkAsRead = (id: string) => {
    markAsRead.mutate(id);
  };

  const handleMarkAllAsRead = () => {
    markAllAsRead.mutate();
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-4 border-b border-gray-200">
        <h2 className="text-lg font-semibold">Notifications</h2>
        {unreadData && unreadData.unread_count > 0 && (
          <button
            onClick={handleMarkAllAsRead}
            className="text-sm text-blue-500 hover:text-blue-600"
          >
            Mark all as read
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-4 text-center text-gray-500">
            Loading...
          </div>
        ) : notificationsData && notificationsData.items.length > 0 ? (
          notificationsData.items.map((notification) => (
            <NotificationItem
              key={notification.id}
              notification={notification}
              onMarkAsRead={handleMarkAsRead}
            />
          ))
        ) : (
          <div className="p-4 text-center text-gray-500">
            No notifications
          </div>
        )}
      </div>

      {unreadData && unreadData.unread_count > 0 && (
        <div className="p-4 border-t border-gray-200 bg-gray-50">
          <span className="text-sm text-gray-600">
            {unreadData.unread_count} unread
          </span>
        </div>
      )}
    </div>
  );
};

export default NotificationCenter;
