import { useTranslation } from "react-i18next";

import { type EntryDraft } from "@/features/report/entry";

/**
 * REP-03: three questions a week asks — what happened, what got in the way, what is next.
 *
 * Each carries the list of what belongs in it, because the sections are broader than the fields
 * they replaced and a student who met the old form knows where "results" used to go and not where
 * it goes now. The hint is part of the question, not decoration.
 *
 * The body text is mono because this is a record of work, and because a monospaced column makes
 * the difference between a sentence and a filled-in field visible at a glance.
 */
export function EntryForm({
  entry,
  onChange,
}: {
  entry: EntryDraft;
  onChange: (entry: EntryDraft) => void;
}) {
  const { t } = useTranslation();
  const field = (key: keyof EntryDraft, label: string, hint: string, rows = 5) => (
    <div>
      <label className="field-label" htmlFor={`${entry.project_id}-${key}`}>
        {label}
      </label>
      <p className="stamp mb-1.5" id={`${entry.project_id}-${key}-hint`}>
        {hint}
      </p>
      <textarea
        id={`${entry.project_id}-${key}`}
        aria-describedby={`${entry.project_id}-${key}-hint`}
        rows={rows}
        value={entry[key]}
        onChange={(event) => onChange({ ...entry, [key]: event.target.value })}
        className="textarea"
      />
    </div>
  );

  return (
    <div className="mt-5 grid gap-5">
      {field("progress", t("report.fields.progress"), t("report.fields.progressHint"), 6)}
      {field("challenges", t("report.fields.challenges"), t("report.fields.challengesHint"), 4)}
      {field("next_plan_text", t("report.fields.nextSteps"), t("report.fields.nextStepsHint"), 4)}
    </div>
  );
}
