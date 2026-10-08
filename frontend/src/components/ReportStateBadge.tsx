/**
 * A weekly report's workflow state as a chip (REP-05).
 *
 * Shared because three screens list reports, and a state that reads in one tone on the professor's
 * list and another on the student's home is a state nobody trusts.
 */
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/evidence/Badges";

const TONE: Record<string, "good" | "warn" | "neutral"> = {
  reviewed: "good",
  revision_requested: "warn",
};

export function ReportStateBadge({ state }: { state: string }) {
  const { t } = useTranslation();
  return (
    <Badge tone={TONE[state] ?? "neutral"} data-testid="report-state-chip">
      {t(`report.state.${state}`, { defaultValue: state })}
    </Badge>
  );
}
