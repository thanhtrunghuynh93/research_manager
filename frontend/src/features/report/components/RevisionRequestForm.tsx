/**
 * Ask for one project's entry to be revised (REP-05).
 *
 * `POST /reports/{id}/revisions` has existed since the reporting module did, with no caller: the
 * professor could read that a week needed work and had no way to say so, and the student's home
 * screen has been rendering `revision_requested` for a state nothing could produce.
 *
 * The reason is required here as well as at the API, for the same reason `ReviewPage` requires a
 * rationale before an override: a rule the form teaches is better than a rule the round trip
 * enforces, and a request with no reason is one the student cannot act on.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Failure } from "@/components/Failure";
import { useRequestRevision } from "@/features/report/queries";

export function RevisionRequestForm({
  reportId,
  projectId,
  periodId,
  studentId,
}: {
  reportId: string;
  projectId: string;
  periodId: string;
  studentId?: string;
}) {
  const { t } = useTranslation();
  const ask = useRequestRevision(reportId, { periodId, studentId });
  const [reason, setReason] = useState("");
  // Closed until asked for. Open by default, every entry carried a text box and a button that
  // did nothing until typed in, which made reading a report look like filling in a form.
  const [open, setOpen] = useState(false);

  return (
    <form
      className="mt-4 border-t border-border pt-3.5"
      onSubmit={(event) => {
        event.preventDefault();
        if (!reason.trim()) return;
        ask.mutate(
          { project_id: projectId, reason: reason.trim() },
          {
            onSuccess: () => {
              setReason("");
              setOpen(false);
            },
          },
        );
      }}
    >
      {open ? (
        <label className="block">
          <span className="field-label">{t("report.reader.requestRevision")}</span>
          <textarea
            rows={2}
            autoFocus
            value={reason}
            placeholder={t("report.reader.revisionPlaceholder")}
            onChange={(event) => setReason(event.target.value)}
            className="input"
          />
        </label>
      ) : null}
      <div className="flex flex-wrap items-center gap-4" style={{ marginTop: open ? 10 : 0 }}>
        {open ? (
          <>
            <button
              type="submit"
              disabled={ask.isPending || reason.trim() === ""}
              className="btn-primary"
              data-testid={`request-revision-${projectId}`}
            >
              {t("report.reader.sendRevision")}
            </button>
            <button type="button" className="btn-quiet" onClick={() => setOpen(false)}>
              {t("report.reader.cancel")}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn-quiet"
            onClick={() => setOpen(true)}
            data-testid={`open-revision-${projectId}`}
          >
            {t("report.reader.askRevision")}
          </button>
        )}
        {ask.isSuccess && !open ? (
          <span className="stamp" role="status">
            {t("report.reader.revisionSent")}
          </span>
        ) : null}
        <Failure error={ask.error} />
      </div>
    </form>
  );
}
