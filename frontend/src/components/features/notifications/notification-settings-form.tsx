import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import NotificationService from "#/api/notification-service/notification-service.api";
import type { NotificationSettings } from "#/api/notification-service/notification-service.types";
import { NotificationType } from "#/api/notification-service/notification-service.types";
import { SettingsSwitch } from "#/components/features/settings/settings-switch";
import { SettingsInput } from "#/components/features/settings/settings-input";
import {
  displayErrorToast,
  displaySuccessToast,
} from "#/utils/custom-toast-handlers";
import { retrieveAxiosErrorMessage } from "#/utils/retrieve-axios-error-message";

interface NotificationSettingsFormProps {
  className?: string;
}

const defaultNotificationSettings: NotificationSettings = {
  email_enabled: false,
  slack_enabled: false,
  web_push_enabled: true,
  notification_types: {
    [NotificationType.TASK_COMPLETED]: true,
    [NotificationType.TASK_FAILED]: true,
    [NotificationType.TASK_STARTED]: true,
    [NotificationType.LONG_RUNNING_WARNING]: true,
    [NotificationType.SECURITY_ALERT]: true,
    [NotificationType.SYSTEM_MESSAGE]: true,
    [NotificationType.USER_MESSAGE]: true,
    [NotificationType.CONVERSATION_SHARED]: true,
    [NotificationType.MENTION]: true,
  },
  quiet_hours_start: null,
  quiet_hours_end: null,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
};

export const NotificationSettingsForm: React.FC<NotificationSettingsFormProps> = ({
  className = "",
}) => {
  const queryClient = useQueryClient();

  const { data: preferences, isLoading } = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () => NotificationService.getPreferences(),
    staleTime: 1000 * 60 * 5,
  });

  const updatePreferences = useMutation({
    mutationFn: (settings: NotificationSettings) =>
      NotificationService.updatePreferences(settings),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-preferences"] });
      displaySuccessToast("Settings saved");
    },
    onError: (error) => {
      const errorMessage = retrieveAxiosErrorMessage(error);
      displayErrorToast(errorMessage || "An error occurred");
    },
  });

  const settings = preferences?.settings || defaultNotificationSettings;

  const [emailEnabled, setEmailEnabled] = React.useState(
    settings.email_enabled,
  );
  const [webPushEnabled, setWebPushEnabled] = React.useState(
    settings.web_push_enabled,
  );
  const [quietHoursStart, setQuietHoursStart] = React.useState(
    settings.quiet_hours_start || "",
  );
  const [quietHoursEnd, setQuietHoursEnd] = React.useState(
    settings.quiet_hours_end || "",
  );

  React.useEffect(() => {
    if (preferences?.settings) {
      setEmailEnabled(preferences.settings.email_enabled);
      setWebPushEnabled(preferences.settings.web_push_enabled);
      setQuietHoursStart(preferences.settings.quiet_hours_start || "");
      setQuietHoursEnd(preferences.settings.quiet_hours_end || "");
    }
  }, [preferences]);

  const handleSave = () => {
    const newSettings: NotificationSettings = {
      ...settings,
      email_enabled: emailEnabled,
      web_push_enabled: webPushEnabled,
      quiet_hours_start: quietHoursStart || null,
      quiet_hours_end: quietHoursEnd || null,
    };
    updatePreferences.mutate(newSettings);
  };

  if (isLoading) {
    return (
      <div className={`flex flex-col gap-4 ${className}`}>
        <div className="animate-pulse h-6 bg-gray-200 rounded w-1/3" />
        <div className="animate-pulse h-10 bg-gray-200 rounded" />
      </div>
    );
  }

  return (
    <div className={`flex flex-col gap-6 ${className}`}>
      <div className="flex flex-col gap-4">
        <h3 className="text-md font-semibold">Notification Settings</h3>

        <SettingsSwitch
          name="notification-email-enabled"
          onToggle={(checked) => setEmailEnabled(checked)}
          isToggled={emailEnabled}
        >
          Email Notifications
        </SettingsSwitch>

        <SettingsSwitch
          name="notification-web-push-enabled"
          onToggle={(checked) => setWebPushEnabled(checked)}
          isToggled={webPushEnabled}
        >
          Browser Notifications
        </SettingsSwitch>

        <div className="flex flex-col gap-2">
          <label className="text-sm font-medium text-gray-700">
            Quiet Hours
          </label>
          <div className="flex items-center gap-2">
            <SettingsInput
              name="quiet-hours-start"
              label="Start"
              type="time"
              value={quietHoursStart}
              onChange={(value) => setQuietHoursStart(value)}
              className="w-32"
            />
            <span className="text-gray-500">-</span>
            <SettingsInput
              name="quiet-hours-end"
              label="End"
              type="time"
              value={quietHoursEnd}
              onChange={(value) => setQuietHoursEnd(value)}
              className="w-32"
            />
          </div>
          <p className="text-xs text-gray-500">
            Notifications will be silenced during these hours
          </p>
        </div>
      </div>

      <button
        onClick={handleSave}
        disabled={updatePreferences.isPending}
        className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
      >
        {updatePreferences.isPending ? "Saving..." : "Save Settings"}
      </button>
    </div>
  );
};

export default NotificationSettingsForm;
