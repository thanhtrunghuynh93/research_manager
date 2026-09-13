/**
 * A citation the reader can actually follow (QA-03).
 *
 * Two cases are rendered differently on purpose. A citation whose source is no longer visible to
 * this reader is shown as unavailable rather than removed, because a claim that quietly loses its
 * support reads exactly like one that never needed any (architecture §6.3). A professor-only note
 * is shown locked, so the professor knows it informed the answer and a draft for a student never
 * carries it (QA-06).
 */
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

export type Citation = {
  source_kind: string;
  source_id: string;
  source_version?: string;
  locator?: string;
  label?: string;
  available?: boolean;
};

export function CitationLink({ citation }: { citation: Citation }) {
  const { t } = useTranslation();
  const label = citation.label || `${citation.source_kind} ${citation.source_id.slice(0, 8)}`;

  if (citation.available === false) {
    return (
      <span className="text-xs text-muted-foreground line-through" data-testid="citation-gone">
        {label} — {t("evidence.noLongerAvailable")}
      </span>
    );
  }

  if (citation.source_kind === "supervision_note") {
    return (
      <span className="text-xs text-muted-foreground" data-testid="citation-private">
        🔒 {t("evidence.privateNote")}
      </span>
    );
  }

  if (!citation.locator) {
    return (
      <span className="text-xs text-muted-foreground" data-testid="citation-plain">
        {label}
      </span>
    );
  }

  return (
    <Link to={citation.locator} className="text-xs underline" data-testid="citation-link">
      {label}
      {citation.source_version ? ` @${citation.source_version.slice(0, 8)}` : ""}
    </Link>
  );
}

export function CitationList({ citations }: { citations: Citation[] }) {
  const { t } = useTranslation();
  if (citations.length === 0) {
    return <p className="text-xs text-muted-foreground">{t("evidence.noCitations")}</p>;
  }
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1">
      {citations.map((citation) => (
        <li key={`${citation.source_kind}:${citation.source_id}`}>
          <CitationLink citation={citation} />
        </li>
      ))}
    </ul>
  );
}
