/**
 * One feedback: its text, the weeks it is about, and its files (ADR 0026).
 *
 * A student reaches the published version; a professor the newest draft, with a note when it is
 * ahead of what the student reads. The body is the professor's Markdown, rendered without raw HTML
 * (react-markdown drops it) and with unsafe link schemes stripped. Files are never opened in the
 * page: each is a download from a short-lived link, which is how an uploaded .html stays inert.
 */
import ReactMarkdown from "react-markdown";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { Badge } from "@/components/evidence/Badges";
import { Failure } from "@/components/Failure";
import { useSession } from "@/features/auth/queries";
import { useDownloadAttachment, useFeedback } from "@/features/feedback/queries";
import { formatInstant, formatLocalDate } from "@/lib/dates";

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function FeedbackPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const isStudent = useSession().data?.role === "student";
  const feedback = useFeedback(id);
  const download = useDownloadAttachment();

  if (feedback.isPending) return <p className="stamp">{t("common.loading")}</p>;
  if (feedback.isError) {
    const missing = feedback.error instanceof ApiError && feedback.error.problem.status === 404;
    return (
      <section className="py-6">
        <p role="alert" className="text-sm text-bad">
          {missing ? t("feedback.notFound") : <Failure error={feedback.error} />}
        </p>
        <Link to="/feedback" className="btn-ghost mt-4 inline-block">
          {t("feedback.back")}
        </Link>
      </section>
    );
  }

  const item = feedback.data;
  return (
    <section className="animate-rise-in">
      <header className="border-b border-border pb-5">
        <p className="eyebrow mb-1.5">
          <Link to="/feedback">{t("feedback.title")}</Link>
        </p>
        <h1 className="page-title">{item.title}</h1>
        <p className="mt-2 flex flex-wrap items-center gap-3 text-note text-muted-foreground">
          {!isStudent && (
            <Badge tone={item.status === "draft" ? "warn" : "good"}>
              {t(`feedback.status.${item.status}`)}
            </Badge>
          )}
          <span>
            {item.published_at
              ? t("feedback.publishedOn", { when: formatInstant(item.published_at) })
              : t("feedback.draftNote")}
          </span>
        </p>
        {!isStudent && item.has_unpublished_changes && (
          <p role="status" className="mt-3 text-sm text-warn">
            {t("feedback.aheadOfPublished", {
              version: item.version,
              published: item.published_version,
            })}
          </p>
        )}
      </header>

      <article className="prose-feedback mt-6 max-w-3xl" data-testid="feedback-body">
        <ReactMarkdown>{item.body_markdown}</ReactMarkdown>
      </article>

      {item.reports.length > 0 && (
        <section className="mt-8">
          <h2 className="section-title">{t("feedback.aboutWeeks")}</h2>
          <ul className="mt-2 text-sm">
            {item.reports.map((report) => (
              <li key={report.report_id}>
                {formatLocalDate(report.local_start)} – {formatLocalDate(report.local_end)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {item.attachments.length > 0 && (
        <section className="mt-8">
          <h2 className="section-title">{t("feedback.attachments")}</h2>
          <ul className="panel mt-2.5">
            {item.attachments.map((file) => (
              <li
                key={file.attachment_id}
                className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 last:border-b-0"
              >
                <span>
                  {file.filename}{" "}
                  <span className="text-note text-muted-foreground">{size(file.byte_size)}</span>
                </span>
                <button
                  type="button"
                  className="btn-ghost"
                  disabled={download.isPending}
                  onClick={() => download.mutate(file.attachment_id)}
                >
                  {t("feedback.download")}
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-2">
            <Failure error={download.error} />
          </p>
        </section>
      )}
    </section>
  );
}
