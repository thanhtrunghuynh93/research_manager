/**
 * The professor assistant (QA-01..07).
 *
 * The layout carries the answer contract rather than decorating it. Computed facts, model
 * synthesis, and suggestions are three visually distinct blocks, because QA-03 makes the
 * distinction a product commitment and a single flowing paragraph would erase it. Gaps are shown
 * as prominently as the answer: "what I could not establish" is the part a busy reader most needs
 * and would otherwise never scroll to.
 *
 * The active scope is always on screen (QA-05), and a clarifying question replaces the answer
 * rather than accompanying it — there is nothing to read yet.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/evidence/Badges";
import { CitationList } from "@/components/evidence/CitationLink";
import { useAsk } from "@/features/assistant/queries";
import { formatInstant } from "@/lib/dates";

export function AssistantPage() {
  const { t } = useTranslation();
  const [question, setQuestion] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const ask = useAsk();

  // Pydantic defaults surface as optional in the generated schema; normalise once so the render
  // below reads as the answer contract rather than as a chain of guards.
  const raw = ask.data;
  const answer = raw && {
    ...raw,
    facts: raw.facts ?? [],
    synthesis: raw.synthesis ?? [],
    suggestions: raw.suggestions ?? [],
    citations: raw.citations ?? [],
    gaps: raw.gaps ?? [],
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!question.trim()) return;
    ask.mutate(
      { question, conversation_id: conversationId },
      {
        onSuccess: () => setQuestion(""),
        // A conversation the server will not accept — deleted, or from another session — would
        // otherwise fail every later question in this tab. Drop it and let the next one start
        // a fresh conversation.
        onError: () => setConversationId(null),
      },
    );
  };

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{t("assistant.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("assistant.readOnly")}</p>
      </header>

      <form onSubmit={submit} className="flex gap-2">
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={t("assistant.placeholder")}
          aria-label={t("assistant.question")}
          className="flex-1 rounded-md border border-border px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={ask.isPending}
          className="rounded-md border border-border px-3 py-2 text-sm font-medium disabled:opacity-50"
        >
          {ask.isPending ? t("assistant.thinking") : t("assistant.ask")}
        </button>
      </form>

      {ask.isError && <p className="text-sm text-muted-foreground">{t("assistant.failed")}</p>}

      {answer && (
        <article className="space-y-5" data-testid="answer">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge data-testid="scope-badge">
              {t("assistant.scope")}: {scopeLabel(answer, t)}
            </Badge>
            <Badge>{answer.time_range}</Badge>
            {answer.cached && <Badge tone="neutral">{t("assistant.cached")}</Badge>}
            <span className="text-muted-foreground">
              {formatInstant(answer.generated_at)} · {answer.model_name}
            </span>
          </div>

          {answer.clarifying_question ? (
            <p className="rounded-md border border-border p-4 text-sm" data-testid="clarifying">
              {answer.clarifying_question}
            </p>
          ) : (
            <>
              <p className="whitespace-pre-line text-sm" data-testid="answer-text">
                {answer.answer}
              </p>

              {answer.facts.length > 0 && (
                <div className="space-y-2" data-testid="facts">
                  <h2 className="text-sm font-medium">{t("assistant.facts")}</h2>
                  <p className="text-xs text-muted-foreground">{t("assistant.factsNote")}</p>
                  <ul className="divide-y divide-border rounded-lg border border-border">
                    {answer.facts.map((fact) => (
                      <li key={fact.name} className="px-4 py-2 text-sm">
                        <span className="font-medium">{fact.label}: </span>
                        <span>{renderValue(fact.value)}</span>
                        <p className="text-xs text-muted-foreground">
                          {t("overview.asOf", { when: formatInstant(fact.as_of) })}
                          {fact.note ? ` — ${fact.note}` : ""}
                        </p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {answer.synthesis.length > 0 && (
                <div className="space-y-2" data-testid="synthesis">
                  <h2 className="text-sm font-medium">{t("assistant.synthesis")}</h2>
                  <p className="text-xs text-muted-foreground">{t("assistant.synthesisNote")}</p>
                  <ul className="list-disc space-y-1 pl-5 text-sm">
                    {answer.synthesis.map((line, index) => (
                      <li key={index}>{line}</li>
                    ))}
                  </ul>
                </div>
              )}

              {answer.suggestions.length > 0 && (
                <div className="space-y-2" data-testid="suggestions">
                  <h2 className="text-sm font-medium">{t("assistant.suggestions")}</h2>
                  <p className="text-xs text-muted-foreground">{t("assistant.suggestionsNote")}</p>
                  <ul className="list-disc space-y-1 pl-5 text-sm">
                    {answer.suggestions.map((line, index) => (
                      <li key={index}>{line}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="space-y-2">
                <h2 className="text-sm font-medium">{t("assistant.citations")}</h2>
                <CitationList citations={answer.citations} />
              </div>
            </>
          )}

          {answer.gaps.length > 0 && (
            <div
              className="space-y-1 rounded-md border border-amber-300 bg-amber-50 p-4 dark:bg-amber-950"
              data-testid="gaps"
            >
              <h2 className="text-sm font-medium">{t("assistant.gaps")}</h2>
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {answer.gaps.map((gap, index) => (
                  <li key={index}>{gap}</li>
                ))}
              </ul>
            </div>
          )}

          {!conversationId && answer.conversation_id && (
            <button
              type="button"
              // The conversation, not `answer.id`: that one is minted per answer and is not
              // something `AskIn.conversation_id` can resolve (QA-05).
              onClick={() => setConversationId(answer.conversation_id ?? null)}
              className="text-xs underline"
            >
              {t("assistant.keepScope")}
            </button>
          )}
        </article>
      )}
    </section>
  );
}

function scopeLabel(
  answer: { scope: Record<string, unknown> },
  t: (key: string) => string,
): string {
  const parts = [answer.scope.student_name, answer.scope.project_name].filter(Boolean);
  return parts.length ? parts.map(String).join(" · ") : t("assistant.wholeWorkspace");
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, count]) => `${key}: ${String(count)}`)
      .join(", ");
  }
  return String(value);
}
