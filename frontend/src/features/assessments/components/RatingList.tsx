/**
 * The four rubric dimensions as they stand, read-only (ASSESS-03, ASSESS-08).
 *
 * This is the professor's third pane with the `<select>` removed, and it is kept as a separate
 * component rather than a mode of that one on purpose: merging them would put an approve control
 * one boolean away from a student's screen. The rating shown is the *effective* one, so an
 * override reads as the decision it is rather than sitting beside the model's original.
 */
import { useTranslation } from "react-i18next";

import { DIMENSIONS, ratingOf, type Assessment } from "@/features/assessments/types";

export function RatingList({ assessment }: { assessment: Assessment }) {
  const { t } = useTranslation();

  return (
    <ul className="grid gap-2.5" data-testid="my-ratings">
      {DIMENSIONS.map((dimension) => {
        const rating = ratingOf(assessment, dimension);
        const value = rating?.rating;
        return (
          <li key={dimension} className="card">
            <div className="flex items-center justify-between gap-2.5">
              <span className="text-ui font-medium">{t(`assessment.dimension.${dimension}`)}</span>
              <span className="font-mono text-ui">
                {value === undefined || value === null || value === "unknown"
                  ? t("assessment.unknown")
                  : String(value)}
              </span>
            </div>
            {rating?.rationale ? (
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                {rating.rationale}
              </p>
            ) : null}
            {(rating?.validation_notes ?? []).map((note, index) => (
              <p key={index} className="mt-1.5 text-meta leading-relaxed text-warn">
                {note}
              </p>
            ))}
          </li>
        );
      })}
    </ul>
  );
}
