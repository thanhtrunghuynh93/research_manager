/** The shape of one project entry while it is being edited (REP-03).
 *
 * Kept out of the component file so the form stays a component module.
 */
import type { components } from "@/api/generated/schema";

export type EntryDraft = {
  project_id: string;
  stage: string;
  work_performed: string;
  results: string;
  deviations: string;
  next_plan_text: string;
  questions: string;
  hours: string;
};

export function emptyEntry(projectId: string, stage: string): EntryDraft {
  return {
    project_id: projectId,
    stage,
    work_performed: "",
    results: "",
    deviations: "",
    next_plan_text: "",
    questions: "",
    hours: "",
  };
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
 * The inverse of what `ReportEditorPage.onSubmit` sends, and `hours` is a number on the wire and a
 * string in the form because an empty box is not zero.
 */
export function draftOfEntry(entry: components["schemas"]["EntryOut"]): EntryDraft {
  return {
    project_id: String(entry.project_id),
    stage: entry.stage,
    work_performed: entry.work_performed,
    results: entry.results,
    deviations: entry.deviations,
    next_plan_text: textOfPlan(entry.next_plan),
    questions: entry.questions,
    hours: entry.hours === null || entry.hours === undefined ? "" : String(entry.hours),
  };
}
