import { useTranslation } from "react-i18next";

import type { AutosaveState } from "@/hooks/useAutosave";
import { formatTimeOfDay } from "@/lib/dates";

export function AutosaveIndicator({
  state,
  savedAt,
  timezone,
}: {
  state: AutosaveState;
  savedAt: Date | null;
  /** The workspace's zone — the same one the deadline on this screen is written in. */
  timezone?: string;
}) {
  const { t } = useTranslation();
  const text =
    state === "saving"
      ? t("report.autosave.saving")
      : state === "error"
        ? t("report.autosave.failed")
        : savedAt
          ? `${t("report.autosave.saved")} ${formatTimeOfDay(savedAt, timezone)}`
          : t("report.autosave.idle");

  return (
    <span
      data-testid="autosave-indicator"
      className={
        state === "error"
          ? "font-mono text-ui text-bad"
          : state === "saving"
            ? "font-mono text-ui text-warn"
            : "font-mono text-ui text-muted-foreground"
      }
    >
      {text}
    </span>
  );
}
