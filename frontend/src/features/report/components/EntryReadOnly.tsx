/**
 * One submitted entry, as text (REP-03).
 *
 * The same six fields in the same order as `EntryForm`, under the same labels, so a student
 * reading back what they sent recognises the shape of what they typed. A field left empty is
 * shown as empty rather than dropped: "nothing was written under deviations" is a fact about the
 * week, and a form that silently omits its empty fields reads as though they were never asked.
 */
import { useTranslation } from "react-i18next";

import { textOfPlan } from "@/features/report/entry";
import type { EntryOut } from "@/features/report/types";

export function EntryReadOnly({ entry }: { entry: EntryOut }) {
  const { t } = useTranslation();

  const field = (label: string, value: string) => (
    <div>
      <p className="field-label">{label}</p>
      {value ? (
        <p className="mt-1 font-mono text-ui leading-relaxed whitespace-pre-wrap">{value}</p>
      ) : (
        <p className="mt-1 text-ui text-faint">{t("report.reader.nothingWritten")}</p>
      )}
    </div>
  );

  return (
    <div className="mt-4 grid gap-4">
      {field(t("report.fields.workPerformed"), entry.work_performed)}
      {field(t("report.fields.results"), entry.results)}
      {field(t("report.fields.deviations"), entry.deviations)}
      {field(t("report.fields.nextPlan"), textOfPlan(entry.next_plan))}
      {field(t("report.fields.questions"), entry.questions)}
      <p className="stamp">
        {entry.hours === null || entry.hours === undefined
          ? t("report.reader.noHours")
          : t("report.reader.hours", { hours: entry.hours })}
      </p>
    </div>
  );
}
