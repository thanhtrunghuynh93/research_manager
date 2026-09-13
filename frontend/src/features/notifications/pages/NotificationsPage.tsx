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
    <section className="max-w-2xl animate-rise-in">
      <header>
        <h1 className="page-title">{t("notifications.title")}</h1>
      </header>

      <ul className="panel mt-6" data-testid="list">
        {notifications.data?.map((notification) => (
          <li key={notification.id} className="row items-start">
            <div>
              <p className="text-[13.5px] font-medium">
                {t(`notifications.kind.${notification.kind}`, {
                  defaultValue: notification.kind,
                })}
              </p>
              <p className="stamp mt-1">{formatInstant(notification.created_at)}</p>
            </div>
            {notification.read_at ? (
              <Badge>{t("notifications.read")}</Badge>
            ) : (
              <button
                type="button"
                onClick={() => markRead.mutate(notification.id)}
                className="btn-quiet"
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

      <h2 className="section-title mt-8">{t("notifications.preferences")}</h2>
      <ul className="panel mt-2.5">
        {kinds.map((kind) => {
          const locked = UNMUTABLE.includes(kind);
          return (
            <li key={kind} className="row">
              <span>{t(`notifications.kind.${kind}`, { defaultValue: kind })}</span>
              {locked ? (
                <span className="stamp" data-testid={`locked-${kind}`}>
                  {t("notifications.cannotMute")}
                </span>
              ) : (
                <label className="flex cursor-pointer items-center gap-2 font-mono text-[11.5px] text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={mutedKinds.has(kind)}
                    onChange={(event) => mute.mutate({ kind, muted: event.target.checked })}
                    className="h-4 w-4 accent-accent"
                  />
                  {t("notifications.mute")}
                </label>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
