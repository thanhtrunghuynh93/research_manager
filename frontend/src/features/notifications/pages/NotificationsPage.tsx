/**
 * UI-07: the list, and what the reader may turn off.
 *
 * Notification text arrives already filtered by the recipient's permissions — the server composes
 * it, so there is nothing here that could leak by rendering the wrong field. What this page owes
 * the reader is the distinction between a category they may mute and one they may not, and the
 * reason: a missed deadline and a revision request carry obligations, not news.
 */
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/evidence/Badges";
import {
  useMarkRead,
  useMute,
  useNotifications,
  usePreferences,
} from "@/features/notifications/queries";
import { UNMUTABLE } from "@/features/notifications/types";
import { formatInstant } from "@/lib/dates";

export function NotificationsPage() {
  const { t } = useTranslation();
  const notifications = useNotifications();
  const preferences = usePreferences();
  const markRead = useMarkRead();
  const mute = useMute();

  const mutedKinds = new Set(
    (preferences.data ?? []).filter((row) => row.muted_at).map((row) => row.kind),
  );
  const kinds = Array.from(
    new Set([
      ...UNMUTABLE,
      ...(preferences.data ?? []).map((preference) => preference.kind),
      ...(notifications.data ?? []).map((notification) => notification.kind),
    ]),
  ).sort();

  return (
    <section className="space-y-8">
      <header>
        <h1 className="text-xl font-semibold">{t("notifications.title")}</h1>
      </header>

      <ul className="divide-y divide-border rounded-lg border border-border" data-testid="list">
        {notifications.data?.map((notification) => (
          <li key={notification.id} className="flex items-start justify-between gap-4 px-4 py-3">
            <div className="space-y-1">
              <p className="text-sm font-medium">
                {t(`notifications.kind.${notification.kind}`, {
                  defaultValue: notification.kind,
                })}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatInstant(notification.created_at)}
              </p>
            </div>
            {notification.read_at ? (
              <Badge>{t("notifications.read")}</Badge>
            ) : (
              <button
                type="button"
                onClick={() => markRead.mutate(notification.id)}
                className="text-xs underline"
              >
                {t("notifications.markRead")}
              </button>
            )}
          </li>
        ))}
        {notifications.data?.length === 0 && (
          <li className="px-4 py-3 text-sm text-muted-foreground">{t("notifications.empty")}</li>
        )}
      </ul>

      <div className="space-y-2">
        <h2 className="text-sm font-medium">{t("notifications.preferences")}</h2>
        <ul className="divide-y divide-border rounded-lg border border-border">
          {kinds.map((kind) => {
            const locked = UNMUTABLE.includes(kind);
            return (
              <li key={kind} className="flex items-center justify-between px-4 py-2 text-sm">
                <span>{t(`notifications.kind.${kind}`, { defaultValue: kind })}</span>
                {locked ? (
                  <span className="text-xs text-muted-foreground" data-testid={`locked-${kind}`}>
                    {t("notifications.cannotMute")}
                  </span>
                ) : (
                  <label className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={mutedKinds.has(kind)}
                      onChange={(event) => mute.mutate({ kind, muted: event.target.checked })}
                    />
                    {t("notifications.mute")}
                  </label>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
