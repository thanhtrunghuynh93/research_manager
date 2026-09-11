/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

export type User = components["schemas"]["UserOut"];
export type Role = User["role"];
