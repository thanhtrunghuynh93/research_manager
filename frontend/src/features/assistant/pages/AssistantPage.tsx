/**
 * The professor assistant (QA-01..07).
 *
 * The layout carries the answer contract rather than decorating it. Computed facts, model
 * synthesis, and suggestions are three visually distinct blocks, because QA-03 makes the
 * distinction a product commitment and a single flowing paragraph would erase it. Each block is
 * tagged COMPUTED or MODEL so the provenance survives a reader who only skims. Gaps are shown as
 * prominently as the answer: "what I could not establish" is the part a busy reader most needs
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
    <section className="max-w-3xl animate-rise-in">
      <header>
        <h1 className="page-title">{t("assistant.title")}</h1>
        <p className="mt-2 text-[13.5px] text-muted-foreground">{t("assistant.readOnly")}</p>
      </header>

      <form onSubmit={submit} className="mt-6 flex flex-wrap gap-2">
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={t("assistant.placeholder")}
          aria-label={t("assistant.question")}
          className="min-w-0 flex-1 rounded border border-border-strong bg-surface px-3.5 py-2.5 text-sm"
        />
        <button type="submit" disabled={ask.isPending} className="btn-primary">
          {ask.isPending ? t("assistant.thinking") : t("assistant.ask")}
        </button>
      </form>

      {ask.isError && <p className="mt-4 text-sm text-muted-foreground">{t("assistant.failed")}</p>}

      {answer && (
        <article className="mt-7 animate-rise-in" data-testid="answer">
          <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3.5">
            <Badge data-testid="scope-badge" className="chip chip-accent uppercase">
              {t("assistant.scope")}: {scopeLabel(answer, t)}
            </Badge>
            <Badge>{answer.time_range}</Badge>
            {answer.cached && <Badge tone="neutral">{t("assistant.cached")}</Badge>}
            <span className="stamp">
              {formatInstant(answer.generated_at)} · {answer.model_name}
            </span>
          </div>

          {answer.clarifying_question ? (
            <p className="card mt-5 text-sm" data-testid="clarifying">
              {answer.clarifying_question}
            </p>
          ) : (
            <>
              <p
                className="mt-5 whitespace-pre-line font-display text-[1.1875rem] leading-relaxed [text-wrap:pretty]"
                data-testid="answer-text"
              >
                {answer.answer}
              </p>

              {answer.facts.length > 0 && (
                <div className="mt-7" data-testid="facts">
                  <h2 className="flex items-baseline gap-2.5">
                    <span className="section-title">{t("assistant.facts")}</span>
                    <span className="chip chip-good uppercase">computed</span>
                  </h2>
                  <p className="stamp mt-1.5">{t("assistant.factsNote")}</p>
                  <ul className="panel mt-2.5">
                    {answer.facts.map((fact) => (
                      <li key={fact.name} className="px-4 py-2.5 text-[13.5px]">
                        <span className="font-medium">{fact.label}: </span>
                        <span>{renderValue(fact.value)}</span>
                        <p className="stamp mt-1">
                          {t("overview.asOf", { when: formatInstant(fact.as_of) })}
                          {fact.note ? ` — ${fact.note}` : ""}
                        </p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {answer.synthesis.length > 0 && (
                <div className="mt-6" data-testid="synthesis">
                  <h2 className="flex items-baseline gap-2.5">
                    <span className="section-title">{t("assistant.synthesis")}</span>
                    <span className="chip chip-accent uppercase">model</span>
                  </h2>
                  <p className="stamp mt-1.5">{t("assistant.synthesisNote")}</p>
                  <ul className="mt-2.5 list-disc space-y-1.5 pl-5 text-[13.5px] leading-relaxed">
                    {answer.synthesis.map((line, index) => (
                      <li key={index}>{line}</li>
                    ))}
                  </ul>
                </div>
              )}

              {answer.suggestions.length > 0 && (
                <div className="mt-6" data-testid="suggestions">
                  <h2 className="section-title">{t("assistant.suggestions")}</h2>
                  <p className="stamp mt-1.5">{t("assistant.suggestionsNote")}</p>
                  <ul className="mt-2.5 list-disc space-y-1.5 pl-5 text-[13.5px] leading-relaxed">
                    {answer.suggestions.map((line, index) => (
                      <li key={index}>{line}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="mt-6">
                <h2 className="section-title mb-2.5">{t("assistant.citations")}</h2>
                <CitationList citations={answer.citations} />
              </div>
            </>
          )}

          {answer.gaps.length > 0 && (
            <div className="notice-warn mt-6" data-testid="gaps">
              <h2 className="section-title">{t("assistant.gaps")}</h2>
              <ul className="mt-2 list-disc space-y-1.5 pl-5 text-[13.5px] leading-relaxed">
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
              className="btn-quiet mt-5"
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
