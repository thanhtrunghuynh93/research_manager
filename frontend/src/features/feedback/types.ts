/** What `/api/v1/feedback` returns (ADR 0026). Hand-written: the routes are not in the generated schema yet. */
export type FeedbackStatus = "draft" | "published";

export type FeedbackSummary = {
  feedback_id: string;
  student_id: string;
  project_id: string;
  report_ids: string[];
  title: string;
  version: number;
  status: FeedbackStatus;
  published_version: number | null;
  has_unpublished_changes: boolean;
  attachment_count: number;
  updated_at: string;
  published_at: string | null;
  view_url: string;
};

export type FeedbackListPage = { items: FeedbackSummary[]; next_cursor: string | null };

export type FeedbackAttachment = {
  attachment_id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  sha256: string;
};

export type FeedbackReportRef = {
  report_id: string;
  period_id: string;
  local_start: string;
  local_end: string;
};

export type Feedback = {
  feedback_id: string;
  student_id: string;
  project_id: string;
  reports: FeedbackReportRef[];
  title: string;
  body_markdown: string;
  version: number;
  status: FeedbackStatus;
  published_version: number | null;
  has_unpublished_changes: boolean;
  attachments: FeedbackAttachment[];
  updated_at: string;
  published_at: string | null;
};

export type FeedbackDownload = { url: string; filename: string; expires_in: number };
