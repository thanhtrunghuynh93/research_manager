/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

export type Review = components["schemas"]["ReviewOut"];
export type SnapshotItem = components["schemas"]["SnapshotItemOut"];

// The assessment itself is read by the student too, so its type and the rule for which rating
// stands live in `features/assessments/` and are re-exported here. One definition, because a
// second copy of `ratingOf` is how a student ends up shown a rating the professor overrode.
export type { Assessment, Dimension, Rating } from "@/features/assessments/types";
export { DIMENSIONS, ratingOf } from "@/features/assessments/types";
