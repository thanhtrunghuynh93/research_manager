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
      className={state === "error" ? "text-sm text-red-600" : "text-sm text-muted-foreground"}
    >
      {text}
    </span>
  );
}
