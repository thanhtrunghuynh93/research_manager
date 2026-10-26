/**
 * Feedback, newest first (ADR 0026).
 *
 * A student's list holds only what a professor published to them. A professor's holds every
 * feedback in the workspace, drafts included, because the API's visibility rules say so — the page
 * only labels which is which. Writing happens through the MCP connector, not here.
 */
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Badge } from "@/components/evidence/Badges";
import { Failure } from "@/components/Failure";
import { useSession } from "@/features/auth/queries";
import { useFeedbackPages } from "@/features/feedback/queries";
import { formatInstant } from "@/lib/dates";

export function FeedbackListPage() {
  const { t } = useTranslation();
  const isStudent = useSession().data?.role === "student";
  const feedback = useFeedbackPages();
  const items = feedback.data?.items ?? [];

  return (
    <section className="animate-rise-in">
      <header className="border-b border-border pb-5">
        <p className="eyebrow mb-1.5">{t("feedback.eyebrow")}</p>
        <h1 className="page-title">{t("feedback.title")}</h1>
        <p className="mt-2 max-w-2xl text-prose text-muted-foreground">
          {isStudent ? t("feedback.introStudent") : t("feedback.intro")}
        </p>
      </header>

      {feedback.isPending ? <p className="stamp mt-4">{t("common.loading")}</p> : null}
      {feedback.isError ? (
        <p className="mt-4">
          <Failure error={feedback.error} />
        </p>
      ) : null}
      {feedback.data && items.length === 0 ? (
        <p className="mt-6 text-sm text-muted-foreground" data-testid="feedback-empty">
          {isStudent ? t("feedback.noneYetStudent") : t("feedback.noneYet")}
        </p>
      ) : null}

      {items.length > 0 ? (
        <ul className="panel mt-6">
          {items.map((item) => (
            <li key={item.feedback_id} className="border-b border-border last:border-b-0">
              <Link
                to={`/feedback/${item.feedback_id}`}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
              >
                <span className="font-medium">{item.title}</span>
                <span className="flex items-center gap-3 text-note text-muted-foreground">
                  {!isStudent && (
                    <Badge tone={item.status === "draft" ? "warn" : "good"}>
                      {item.has_unpublished_changes
                        ? t("feedback.unpublishedChanges")
                        : t(`feedback.status.${item.status}`)}
                    </Badge>
                  )}
                  {item.attachment_count > 0 && (
                    <span>{t("feedback.files", { count: item.attachment_count })}</span>
                  )}
                  <span>{formatInstant(item.published_at ?? item.updated_at)}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}

      {feedback.hasNextPage ? (
        <button
          type="button"
          onClick={() => void feedback.fetchNextPage()}
          disabled={feedback.isFetchingNextPage}
          className="btn-ghost mt-6"
        >
          {feedback.isFetchingNextPage ? t("common.loading") : t("reports.loadMore")}
        </button>
      ) : null}
    </section>
  );
}
