import { useTranslation } from "react-i18next";

import { hoursProblem, type EntryDraft } from "@/features/report/entry";

/**
 * REP-03: the fields the template requires, in the order the specification lists them.
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
  const problem = hoursProblem(entry.hours);
  const field = (key: keyof EntryDraft, label: string, rows = 4) => (
    <div>
      <label className="field-label" htmlFor={`${entry.project_id}-${key}`}>
        {label}
      </label>
      <textarea
        id={`${entry.project_id}-${key}`}
        rows={rows}
        value={entry[key]}
        onChange={(event) => onChange({ ...entry, [key]: event.target.value })}
        className="textarea"
      />
    </div>
  );

  return (
    <div className="mt-5 grid gap-5">
      {field("work_performed", t("report.fields.workPerformed"))}
      {field("results", t("report.fields.results"))}
      {field("deviations", t("report.fields.deviations"), 3)}
      {field("next_plan_text", t("report.fields.nextPlan"), 3)}
      {field("questions", t("report.fields.questions"), 2)}
      <div>
        <label className="field-label" htmlFor={`${entry.project_id}-hours`}>
          {t("report.fields.hours")}
        </label>
        {/* `step` is deliberately "any" rather than 0.5. The server accepts any value in [0, 168],
            so a half-hour step marked 3.75 — three quarters of an hour — as invalid for a figure
            it would have stored happily. The bounds are the server's and are enforced before the
            submission goes out; see `hoursProblem`. */}
        <input
          id={`${entry.project_id}-hours`}
          type="number"
          min={0}
          max={168}
          step="any"
          value={entry.hours}
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? `${entry.project_id}-hours-error` : undefined}
          onChange={(event) => onChange({ ...entry, hours: event.target.value })}
          className="input w-28 font-mono"
        />
        {problem ? (
          <p
            id={`${entry.project_id}-hours-error`}
            role="alert"
            className="mt-2 text-[13px] text-bad"
            data-testid="hours-error"
          >
            {t(problem)}
          </p>
        ) : null}
        <p className="stamp mt-2">{t("report.fields.hoursNote")}</p>
      </div>
    </div>
  );
}
