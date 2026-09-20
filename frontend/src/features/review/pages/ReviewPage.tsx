/**
 * UI-05: claims, evidence, and the draft assessment on one screen, with approval on the same page.
 *
 * The three panes exist because the decision needs all three at once. A professor asked to approve
 * a rating while the evidence is on another screen will approve the rating. Two things this page
 * refuses to make easy: approving a changed rating without a reason (ASSESS-08), and reading an
 * index as a grade — it sits beside its components and its confidence, never alone.
 *
 * The panes are numbered in the eyebrow because the order is the argument: claim, then evidence,
 * then judgement.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import {
  Badge,
  ConfidenceBadge,
  ConfidenceReasons,
  ProgressIndex,
} from "@/components/evidence/Badges";
import { useUser } from "@/features/people/queries";
import { useAllPeriods, useProjects } from "@/features/report/queries";
import { useApprove, useAssessment, useAssessmentEvidence } from "@/features/review/queries";
import { DIMENSIONS, ratingOf } from "@/features/review/types";
import { useTimezone } from "@/features/calendar/queries";
import { formatInstant, formatLocalDate } from "@/lib/dates";

/** Claim status earns a coloured edge on the card — the reader scans the edges first. */
const CLAIM_EDGE: Record<string, string> = {
  supported: "border-l-good",
  partially_supported: "border-l-warn-rule",
  unsupported: "border-l-bad",
  unverifiable: "border-l-bad",
};

export function ReviewPage() {
  const { t } = useTranslation();
  const { assessmentId } = useParams<{ assessmentId: string }>();
  const assessment = useAssessment(assessmentId);
  const evidence = useAssessmentEvidence(assessmentId);
  const approve = useApprove(assessmentId ?? "");
  const timezone = useTimezone();
  const student = useUser(assessment.data?.student_id);
  const projects = useProjects();
  const periods = useAllPeriods();

  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [rationale, setRationale] = useState("");

  if (assessment.isPending) return <p className="stamp">{t("common.loading")}</p>;
  if (assessment.isError)
    return <p className="text-sm text-muted-foreground">{t("review.unavailable")}</p>;

  const data = assessment.data;
  const period = periods.data?.find((one) => one.id === data.period_id);
  const week = period
    ? `${formatLocalDate(period.local_start)} – ${formatLocalDate(period.local_end)}`
    : "";
  const project = projects.data?.items.find((one) => one.id === data.project_id)?.title ?? "";
  const changed = Object.keys(overrides).length > 0;
  const blocked = changed && rationale.trim().length === 0;
  const narrative = (data.narrative ?? {}) as Record<string, unknown>;

  const submit = () => {
    if (blocked) return;
    approve.mutate({
      override: changed
        ? {
            ratings: Object.fromEntries(
              Object.entries(overrides).map(([dimension, value]) => [
                dimension,
                { rating: value === "unknown" ? "unknown" : Number(value) },
              ]),
            ),
          }
        : null,
      rationale: changed ? rationale : undefined,
    });
  };

  return (
    <section className="animate-rise-in">
      <header className="border-b border-border pb-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            {/* Whose work this is, and for which week. The page said only "Review", while the
                payload carried all three ids — so a professor could approve and publish an
                assessment from a screen that never named the student it was about. */}
            <p className="eyebrow mb-1.5">{t("review.title")}</p>
            <h1 className="page-title">{student.data?.display_name ?? t("review.subject")}</h1>
            <p className="mt-2 font-mono text-ui text-muted-foreground">
              {week} {project ? `on ${project}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{t("review.version", { n: data.version_no })}</Badge>
            <ConfidenceBadge
              confidence={data.confidence}
              reasons={(data.confidence_reasons ?? []).map(String)}
            />
            {data.review_state ? (
              <Badge tone={data.review_state === "approved" ? "good" : "neutral"}>
                {t(`review.state.${data.review_state}`, { defaultValue: data.review_state })}
              </Badge>
            ) : null}
            {/* What made the confidence low, on the page. The professor deciding whether to
                approve this draft is exactly the reader who needs it, and it was a tooltip. */}
            <ConfidenceReasons
              reasons={(data.confidence_reasons ?? []).map(String)}
              className="w-full text-right"
            />
          </div>
        </div>
        {/* The index never stands on its own line: it sits on its scale, with the caveat attached. */}
        <div className="mt-4 flex items-end gap-4">
          <ProgressIndex value={data.progress_index} size="figure" />
          <div className="max-w-sm flex-1 pb-1.5">
            {/* No scale without a number on it: an empty meter beside "Not rated" reads as a
                score of zero, which is the one thing an unrated week does not mean. */}
            {data.progress_index === null || data.progress_index === undefined ? null : (
              <span className="meter">
                <span
                  className="meter-fill"
                  style={{ width: `${Math.max(0, Math.min(100, data.progress_index))}%` }}
                />
              </span>
            )}
            <p className="stamp mt-1.5">
              Progress index — read beside its components and its confidence, never alone.
            </p>
          </div>
        </div>
      </header>

      <div className="mt-7 grid gap-6 [grid-template-columns:repeat(auto-fit,minmax(300px,1fr))]">
        {/* Pane one: what the student claimed, and how each claim fared. */}
        <div>
          <p className="eyebrow mb-2.5">1 · {t("review.claims")}</p>
          <ul className="grid gap-2.5" data-testid="claims">
            {((narrative.discrepancies ?? []) as Record<string, unknown>[]).map((item, index) => (
              <li
                key={index}
                className={`card border-l-[3px] ${
                  CLAIM_EDGE[String(item.status)] ?? "border-l-border-strong"
                }`}
              >
                <p className="text-prose leading-relaxed">{String(item.claim ?? "")}</p>
                <Badge tone={item.status === "supported" ? "good" : "warn"} className="mt-2.5">
                  {t(`review.claimStatus.${String(item.status)}`, {
                    defaultValue: String(item.status),
                  })}
                </Badge>
              </li>
            ))}
            {((narrative.discrepancies ?? []) as unknown[]).length === 0 && (
              <li className="text-sm text-muted-foreground">{t("review.noDiscrepancies")}</li>
            )}
          </ul>
        </div>

        {/* Pane two: the snapshot, which is the entire basis of the draft. */}
        <div>
          <p className="eyebrow mb-2.5">2 · {t("review.evidence")}</p>
          <ul className="grid gap-2.5" data-testid="evidence">
            {evidence.data?.map((item) => (
              <li key={item.evidence_ref_id} className="card">
                <p className="line-clamp-4 text-note leading-relaxed text-ink2">{item.text}</p>
                <p className="stamp mt-2.5">
                  {item.locator}
                  {item.integration_of_earlier_work ? ` · ${t("review.integrated")}` : ""}
                </p>
              </li>
            ))}
            {evidence.data?.length === 0 && (
              <li className="text-sm text-muted-foreground">{t("review.noEvidence")}</li>
            )}
          </ul>
        </div>

        {/* Pane three: the draft, and the decision. */}
        <div>
          <p className="eyebrow mb-2.5">3 · {t("review.draft")}</p>
          <ul className="grid gap-2.5" data-testid="ratings">
            {DIMENSIONS.map((dimension) => {
              const rating = ratingOf(data, dimension);
              const current = overrides[dimension] ?? String(rating?.rating ?? "unknown");
              return (
                <li key={dimension} className="card">
                  <div className="flex items-center justify-between gap-2.5">
                    <span className="text-ui font-medium">
                      {t(`assessment.dimension.${dimension}`)}
                    </span>
                    <select
                      aria-label={t(`assessment.dimension.${dimension}`)}
                      value={current}
                      onChange={(event) =>
                        setOverrides((previous) => ({
                          ...previous,
                          [dimension]: event.target.value,
                        }))
                      }
                      className="select"
                    >
                      {["0", "1", "2", "3", "4", "unknown"].map((value) => (
                        <option key={value} value={value}>
                          {value === "unknown" ? t("assessment.unknown") : value}
                        </option>
                      ))}
                    </select>
                  </div>
                  <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                    {rating?.rationale}
                  </p>
                  {(rating?.validation_notes ?? []).map((note, index) => (
                    <p key={index} className="mt-1.5 text-meta leading-relaxed text-warn">
                      {note}
                    </p>
                  ))}
                </li>
              );
            })}
          </ul>

          <div className="card mt-3.5">
            <label className="block">
              <span className="field-label">{t("review.rationale")}</span>
              <textarea
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
                rows={3}
                className="textarea font-sans text-ui"
                placeholder={t("review.rationalePlaceholder")}
              />
            </label>
            {blocked && (
              <p className="mt-2 text-xs text-bad" data-testid="rationale-required">
                {t("review.rationaleRequired")}
              </p>
            )}

            <button
              type="button"
              onClick={submit}
              disabled={blocked || approve.isPending}
              className="btn-primary mt-3 w-full"
            >
              {changed ? t("review.approveWithOverride") : t("review.approve")}
            </button>
            {approve.isSuccess && (
              <p className="mt-2.5 font-mono text-meta text-good" data-testid="published">
                {t("review.published", {
                  when: formatInstant(
                    approve.data.published_at ?? new Date().toISOString(),
                    timezone,
                  ),
                })}
              </p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
