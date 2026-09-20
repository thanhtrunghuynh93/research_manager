/**
 * One submitted entry, as text (REP-03).
 *
 * The same sections in the same order as `EntryForm`, under the same labels, so a student reading
 * back what they sent recognises the shape of what they typed. A section left empty is shown as
 * empty rather than dropped: "nothing was written under challenges" is a fact about the week, and
 * a form that silently omits its empty fields reads as though they were never asked.
 *
 * Results and questions are the exception, and they are shown only when a week actually has them.
 * They were fields of the five-part template and are not asked for any more; a week submitted
 * under it keeps them, and rendering them as empty on every week since would be asking a reader
 * to notice the absence of a question nobody was asked.
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
      {field(t("report.fields.progress"), entry.work_performed)}
      {entry.results ? field(t("report.fields.results"), entry.results) : null}
      {field(t("report.fields.challenges"), entry.deviations)}
      {entry.questions ? field(t("report.fields.questions"), entry.questions) : null}
      {field(t("report.fields.nextSteps"), textOfPlan(entry.next_plan))}
      <p className="stamp">
        {entry.hours === null || entry.hours === undefined
          ? t("report.reader.noHours")
          : t("report.reader.hours", { hours: entry.hours })}
      </p>
    </div>
  );
}
