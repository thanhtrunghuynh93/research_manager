import { useTranslation } from "react-i18next";

import type { AutosaveState } from "@/hooks/useAutosave";

export function AutosaveIndicator({
  state,
  savedAt,
}: {
  state: AutosaveState;
  savedAt: Date | null;
}) {
  const { t } = useTranslation();
  const text =
    state === "saving"
      ? t("report.autosave.saving")
      : state === "error"
        ? t("report.autosave.failed")
        : savedAt
          ? `${t("report.autosave.saved")} ${savedAt.toLocaleTimeString()}`
          : t("report.autosave.idle");

  return (
    <span
      data-testid="autosave-indicator"
      className={
        state === "error"
          ? "font-mono text-[13px] text-bad"
          : state === "saving"
            ? "font-mono text-[13px] text-warn"
            : "font-mono text-[13px] text-muted-foreground"
      }
    >
      {text}
    </span>
  );
}
