/** Types come from the generated OpenAPI schema so the client cannot drift from the API. */
import type { components } from "@/api/generated/schema";

export type Answer = components["schemas"]["AnswerOut"];
export type Conversation = components["schemas"]["ConversationOut"];
export type AnswerFact = components["schemas"]["FactOut"];
