/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

export type Assessment = components["schemas"]["AssessmentOut"];
export type Review = components["schemas"]["ReviewOut"];
export type SnapshotItem = components["schemas"]["SnapshotItemOut"];

export const DIMENSIONS = ["progress", "learning", "rigor", "artifacts"] as const;
export type Dimension = (typeof DIMENSIONS)[number];

export type Rating = {
  rating: number | "unknown" | "not_applicable";
  rationale?: string;
  evidence_ref_ids?: string[];
  validation_notes?: string[];
};

/**
 * What stands for one dimension: the professor's override where there is one, the model's output
 * otherwise. Merged per dimension rather than whole-object, because an override touches the rating
 * the professor changed and must not blank the rationales on the ones they left alone (ASSESS-08).
 */
export function ratingOf(assessment: Assessment, dimension: string): Rating | undefined {
  const original = (assessment.ratings ?? {}) as Record<string, Rating>;
  const effective = (assessment.effective_ratings ?? {}) as Record<string, Rating>;
  const base = original[dimension];
  const override = effective[dimension];
  if (!base) return override;
  return override ? { ...base, ...override } : base;
}
