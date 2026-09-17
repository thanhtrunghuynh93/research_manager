/**
 * UI-02: one released assessment, in full, for the student it is about.
 *
 * The professor's review screen has had an "Approve and publish" button, and a stamp reading
 * "Published to the student", since the assessment pipeline landed. This is the destination that
 * sentence has been naming — until now the publish had nowhere to arrive.
 *
 * Three things are deliberately absent, and each is a disclosure decision rather than an omission:
 *
 * - **No review-state badge.** A student can only ever load an approved assessment, so a badge
 *   that always reads "Approved" would invite the question of what else there is. `Released {{when}}`
 *   says the useful part without implying a draft exists.
 * - **No evidence snapshot.** `GET /assessments/{id}/evidence` would answer, but the items it
 *   returns carry their own visibility and the service does not filter them. UI-02 does not ask for
 *   the snapshot, so the safe thing is not to ask for it either.
 * - **No approve or override control.** Those are the professor's decision, and this page renders
 *   its ratings through a read-only component rather than a disabled version of theirs.
 *
 * What is present is the reply: ASSESS-08 lets the assessed student contest an assessment and put
 * their evidence on the record, and that is what makes this a loop rather than an announcement.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { ConfidenceBadge, ProgressIndex } from "@/components/evidence/Badges";
import { Failure } from "@/components/Failure";
import { RatingList } from "@/features/assessments/components/RatingList";
import {
  useAssessment,
  useFeedback,
  useRequestCorrection,
} from "@/features/assessments/queries";
import { formatInstant } from "@/lib/dates";

export function MyAssessmentPage() {
  const { t } = useTranslation();
  const { assessmentId } = useParams<{ assessmentId: string }>();
  const assessment = useAssessment(assessmentId);

  if (assessment.isPending) return <p className="stamp">{t("common.loading")}</p>;
  // A draft is a 404 for a student by policy, so there is nothing to distinguish here — and
  // saying "this is still in draft" would disclose that one exists.
  if (assessment.isError || !assessment.data)
    return <p className="text-sm text-muted-foreground">{t("myAssessment.unavailable")}</p>;

  const data = assessment.data;

  return (
    <section className="max-w-2xl animate-rise-in">
      <header className="border-b border-border pb-5">
        <p className="eyebrow mb-1.5">{t("myAssessment.title")}</p>
        <h1 className="page-title">
          {t("myAssessment.for", { project: String(data.project_id).slice(0, 8) })}
        </h1>
        {data.published_at ? (
          <p className="stamp mt-2" data-testid="released-at">
            {t("myAssessment.releasedAt", { when: formatInstant(data.published_at) })}
          </p>
        ) : null}
      </header>

      <div className="panel mt-6 flex flex-wrap items-center justify-between gap-5 p-5">
        <div>
          <p className="eyebrow">{t("myAssessment.index")}</p>
          <ProgressIndex value={data.progress_index} size="figure" />
        </div>
        <ConfidenceBadge
          confidence={data.confidence}
          reasons={(data.confidence_reasons ?? []).map(String)}
        />
      </div>
      <p className="stamp mt-2">{t("myAssessment.indexNote")}</p>

      <h2 className="section-title mt-8 mb-2.5">{t("myAssessment.ratings")}</h2>
      <RatingList assessment={data} />

      <FeedbackThread assessmentId={assessmentId!} />
    </section>
  );
}

function FeedbackThread({ assessmentId }: { assessmentId: string }) {
  const { t } = useTranslation();
  const feedback = useFeedback(assessmentId);
  const correction = useRequestCorrection(assessmentId);
  const [body, setBody] = useState("");

  return (
    <>
      <h2 className="section-title mt-8 mb-2.5">{t("myAssessment.feedback")}</h2>
      <ul className="panel" data-testid="feedback">
        {feedback.data?.map((item) => (
          <li key={item.id} className="row">
            <span className="text-[13px] leading-relaxed">{item.body}</span>
            <span className="text-right font-mono text-[11.5px] text-muted-foreground">
              {t(`assessment.feedbackKind.${item.kind}`, { defaultValue: item.kind })} ·{" "}
              {formatInstant(item.created_at)}
            </span>
          </li>
        ))}
        {feedback.data?.length === 0 && (
          <li className="px-4 py-2.5 text-sm text-muted-foreground">
            {t("myAssessment.noFeedback")}
          </li>
        )}
      </ul>

      <form
        className="panel mt-4 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          correction.mutate(body, { onSuccess: () => setBody("") });
        }}
      >
        <label className="block">
          <span className="field-label">{t("myAssessment.correction")}</span>
          <textarea
            rows={3}
            required
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder={t("myAssessment.correctionPlaceholder")}
            className="input"
          />
        </label>
        <div className="mt-3 flex items-center gap-4">
          <button type="submit" disabled={correction.isPending} className="btn-secondary">
            {t("myAssessment.correctionSend")}
          </button>
          {correction.isSuccess ? (
            <span className="stamp" role="status">
              {t("myAssessment.correctionSent")}
            </span>
          ) : null}
          <Failure error={correction.error} />
        </div>
        <p className="stamp mt-3">{t("myAssessment.correctionNote")}</p>
      </form>
    </>
  );
}
