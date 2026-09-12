/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

export type Notification = components["schemas"]["NotificationOut"];
export type Preference = components["schemas"]["PreferenceOut"];

/** UI-07: these carry obligations or decisions and cannot be muted. */
export const UNMUTABLE = ["missed_deadline", "revision_requested", "unfulfilled_obligations"];
