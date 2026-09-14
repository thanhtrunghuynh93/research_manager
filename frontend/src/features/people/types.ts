/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

export type User = components["schemas"]["UserOut"];
export type UserPage = components["schemas"]["Page_UserOut_"];
export type Invitation = components["schemas"]["InvitationOut"];
export type Role = components["schemas"]["Role"];
export type UserState = components["schemas"]["UserState"];
