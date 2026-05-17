import React from "react";
import { Bell } from "lucide-react";
import { useUnreadNotificationCount } from "#/hooks/query/use-notifications";
import { useMarkAllNotificationsAsRead } from "#/hooks/mutation/use-notification-mutations";

export const NotificationBell: React.FC = () => {
  const { data: unreadData } = useUnreadNotificationCount();
  const markAllAsRead = useMarkAllNotificationsAsRead();

  const handleClick = () => {
    if (unreadData && unreadData.unread_count > 0) {
      markAllAsRead.mutate();
    }
  };

  const unreadCount = unreadData?.unread_count ?? 0;

  return (
    <button
      onClick={handleClick}
      className="relative p-2 hover:bg-gray-100 rounded-full transition-colors"
      title="Notifications"
    >
      <Bell className="w-6 h-6" />
      {unreadCount > 0 && (
        <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
          {unreadCount > 9 ? "9+" : unreadCount}
        </span>
      )}
    </button>
  );
};

export default NotificationBell;
