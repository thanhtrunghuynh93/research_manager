/** The shape of one project entry while it is being edited (REP-03).
 *
 * Kept out of the component file so the form stays a component module.
 */
import type { components } from "@/api/generated/schema";

/**
 * Three questions, not five (REP-03).
 *
 * The template asked for work performed, results, deviations, a next-week plan and questions for
 * the professor, and a student filling it in weekly was answering the same thing twice: what was
 * done and what came of it are one account, and a blocker and the question it raises are one
 * problem. Three sections — what happened, what got in the way, what is next — is the same report
 * with the seams taken out.
 *
 * The wire keeps the five names it always had. `progress` is sent as `work_performed` and
 * `challenges` as `deviations`, because the submitted record of a week is never rewritten
 * (REP-07) and a column renamed underneath it would make every past entry unreadable. What a
 * student typed into "Results" in September is still in the record, under the label they typed it
 * under; `draftOfEntry` folds it into Progress if they open that week again.
 */
export type EntryDraft = {
  project_id: string;
  stage: string;
  progress: string;
  challenges: string;
  next_plan_text: string;
};

export function emptyEntry(projectId: string, stage: string): EntryDraft {
  return {
    project_id: projectId,
    stage,
    progress: "",
    challenges: "",
    next_plan_text: "",
  };
}

/** Two fields that are now one, kept apart by a blank line rather than run together. */
function joined(first: string, second: string): string {
  return [first.trim(), second.trim()].filter(Boolean).join("\n\n");
}

/**
 * The next-week plan, in the shape a plan baseline is frozen from (PROJ-04).
 *
 * `next_plan` is free-form JSON and the editor used to write `{ outcomes: [text] }`, which nothing
 * on the server read: `_carried_plan` takes `items[].planned_outcome`, so every plan a student
 * typed was dropped on its way to becoming next week's baseline and the assessment that followed
 * reported "no plan baseline was in effect". One box means one commitment, and `weight` is left to
 * the server's default because a single item cannot be weighted against anything.
 */
export function planOfText(text: string): Record<string, unknown> {
  const trimmed = text.trim();
  return trimmed ? { items: [{ planned_outcome: trimmed }] } : {};
}

/** The inverse of `planOfText`, tolerant of the shape earlier clients wrote. */
export function textOfPlan(next_plan: unknown): string {
  if (!next_plan || typeof next_plan !== "object") return "";
  const plan = next_plan as { items?: unknown; outcomes?: unknown };
  if (Array.isArray(plan.items)) {
    const outcomes = plan.items
      .map((item) =>
        item && typeof item === "object"
          ? String((item as { planned_outcome?: unknown }).planned_outcome ?? "")
          : "",
      )
      .filter(Boolean);
    return outcomes.join("\n");
  }
  if (Array.isArray(plan.outcomes)) {
    return plan.outcomes
      .map((outcome) => String(outcome))
      .filter(Boolean)
      .join("\n");
  }
  return "";
}

/**
 * The editable form of an entry that has already been submitted.
 *
 * The inverse of what `ReportEditorPage.onSubmit` sends.
 */
export function draftOfEntry(entry: components["schemas"]["EntryOut"]): EntryDraft {
  return {
    project_id: String(entry.project_id),
    stage: entry.stage,
    // An entry submitted under the five-field template carries text in `results` and `questions`
    // that the form no longer has a box for. Folding them in is what keeps a resubmission from
    // quietly dropping them: the words survive into the new version, under the section that now
    // asks for them. The version they were first submitted in is untouched either way.
    progress: joined(entry.work_performed, entry.results),
    challenges: joined(entry.deviations, entry.questions),
    next_plan_text: textOfPlan(entry.next_plan),
  };
}

/**
 * A saved draft, whichever template it was typed under.
 *
 * `draft_content` is free-form JSON the client writes and reads, so a draft autosaved before the
 * form became three sections is still sitting there in five keys. Read straight, its
 * `work_performed` means nothing to a form asking for `progress`, and the student would have
 * opened the week to find the boxes empty and their own text gone — autosaved, present on the
 * server, and unreachable. So an old draft is folded the same way a submitted entry is.
 */
export function draftOfSaved(value: unknown, projectId: string, stage: string): EntryDraft {
  const saved = (value ?? {}) as Record<string, unknown>;
  const text = (key: string) => String(saved[key] ?? "");
  const current = "progress" in saved || "challenges" in saved;
  return {
    project_id: String(saved.project_id ?? projectId),
    stage: String(saved.stage ?? stage),
    progress: current ? text("progress") : joined(text("work_performed"), text("results")),
    challenges: current ? text("challenges") : joined(text("deviations"), text("questions")),
    next_plan_text: text("next_plan_text"),
  };
}
