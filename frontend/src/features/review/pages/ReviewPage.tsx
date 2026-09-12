/**
 * UI-05: claims, evidence, and the draft assessment on one screen, with approval on the same page.
 *
 * The three panes exist because the decision needs all three at once. A professor asked to approve
 * a rating while the evidence is on another screen will approve the rating. Two things this page
 * refuses to make easy: approving a changed rating without a reason (ASSESS-08), and reading an
 * index as a grade — it sits beside its components and its confidence, never alone.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { Badge, ConfidenceBadge, ProgressIndex } from "@/components/evidence/Badges";
import { useApprove, useAssessment, useAssessmentEvidence } from "@/features/review/queries";
import { DIMENSIONS, ratingOf } from "@/features/review/types";
import { formatInstant } from "@/lib/dates";

export function ReviewPage() {
  const { t } = useTranslation();
  const { assessmentId } = useParams<{ assessmentId: string }>();
  const assessment = useAssessment(assessmentId);
  const evidence = useAssessmentEvidence(assessmentId);
  const approve = useApprove(assessmentId ?? "");

  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [rationale, setRationale] = useState("");

  if (assessment.isPending) return <p className="text-muted-foreground">{t("common.loading")}</p>;
  if (assessment.isError) return <p className="text-muted-foreground">{t("review.unavailable")}</p>;

  const data = assessment.data;
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
    <section className="space-y-6">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{t("review.title")}</h1>
        <Badge>{t("review.version", { n: data.version_no })}</Badge>
        <ConfidenceBadge
          confidence={data.confidence}
          reasons={(data.confidence_reasons ?? []).map(String)}
        />
        <ProgressIndex value={data.progress_index} />
        {data.review_state ? (
          <Badge tone={data.review_state === "approved" ? "good" : "neutral"}>
            {t(`review.state.${data.review_state}`, { defaultValue: data.review_state })}
          </Badge>
        ) : null}
      </header>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Pane one: what the student claimed, and how each claim fared. */}
        <div className="space-y-3">
          <h2 className="text-sm font-medium">{t("review.claims")}</h2>
          <ul className="space-y-2" data-testid="claims">
            {((narrative.discrepancies ?? []) as Record<string, unknown>[]).map((item, index) => (
              <li key={index} className="rounded-md border border-border p-3 text-sm">
                <p>{String(item.claim ?? "")}</p>
                <Badge tone={item.status === "supported" ? "good" : "warn"}>
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
        <div className="space-y-3">
          <h2 className="text-sm font-medium">{t("review.evidence")}</h2>
          <ul className="space-y-2" data-testid="evidence">
            {evidence.data?.map((item) => (
              <li
                key={item.evidence_ref_id}
                className="rounded-md border border-border p-3 text-xs"
              >
                <p className="line-clamp-4">{item.text}</p>
                <p className="mt-1 text-muted-foreground">
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
        <div className="space-y-3">
          <h2 className="text-sm font-medium">{t("review.draft")}</h2>
          <ul className="space-y-3" data-testid="ratings">
            {DIMENSIONS.map((dimension) => {
              const rating = ratingOf(data, dimension);
              const current = overrides[dimension] ?? String(rating?.rating ?? "unknown");
              return (
                <li key={dimension} className="space-y-1 rounded-md border border-border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">
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
                      className="rounded border border-border px-2 py-1 text-sm"
                    >
                      {["0", "1", "2", "3", "4", "unknown"].map((value) => (
                        <option key={value} value={value}>
                          {value === "unknown" ? t("assessment.unknown") : value}
                        </option>
                      ))}
                    </select>
                  </div>
                  <p className="text-xs text-muted-foreground">{rating?.rationale}</p>
                  {(rating?.validation_notes ?? []).map((note, index) => (
                    <p key={index} className="text-xs text-amber-700 dark:text-amber-300">
                      {note}
                    </p>
                  ))}
                </li>
              );
            })}
          </ul>

          <label className="block space-y-1">
            <span className="text-sm font-medium">{t("review.rationale")}</span>
            <textarea
              value={rationale}
              onChange={(event) => setRationale(event.target.value)}
              rows={3}
              className="w-full rounded-md border border-border p-2 text-sm"
              placeholder={t("review.rationalePlaceholder")}
            />
          </label>
          {blocked && (
            <p
              className="text-xs text-rose-700 dark:text-rose-300"
              data-testid="rationale-required"
            >
              {t("review.rationaleRequired")}
            </p>
          )}

          <button
            type="button"
            onClick={submit}
            disabled={blocked || approve.isPending}
            className="rounded-md border border-border px-3 py-1.5 text-sm font-medium disabled:opacity-50"
          >
            {changed ? t("review.approveWithOverride") : t("review.approve")}
          </button>
          {approve.isSuccess && (
            <p className="text-xs text-muted-foreground" data-testid="published">
              {t("review.published", {
                when: formatInstant(approve.data.published_at ?? new Date().toISOString()),
              })}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
