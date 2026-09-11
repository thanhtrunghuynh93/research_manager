/** The shape of one project entry while it is being edited (REP-03).
 *
 * Kept out of the component file so the form stays a component module.
 */

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
