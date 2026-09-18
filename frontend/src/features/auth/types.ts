/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

/**
 * What `/auth/me` answers. `workspace_id` is the one answer to which workspace this account is in:
 * joining moves the account itself, so there is no second, session-level answer (ADR 0014).
 */
export type User = components["schemas"]["UserOut"];
export type Role = User["role"];
