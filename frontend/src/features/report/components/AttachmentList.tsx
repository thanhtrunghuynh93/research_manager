/**
 * The evidence on one entry, read-only (REP-04).
 *
 * The attaching half lives in `Attachments.tsx`; this is what a reader sees. Polling is
 * deliberately off: extraction runs when the week is submitted, so on a week that has been
 * submitted there is nothing left to watch, and a professor's open tab should not ask the server
 * for an unchanged list every three seconds.
 */
import { useTranslation } from "react-i18next";

import { openArtifact, useArtifacts } from "@/features/report/queries";
import { cn } from "@/lib/utils";

export function AttachmentList({
  periodId,
  projectId,
  studentId,
  className,
}: {
  periodId: string;
  projectId: string;
  studentId?: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const artifacts = useArtifacts({ periodId, projectId, studentId }, false);

  if (!artifacts.data?.length) return null;

  return (
    <div className={cn(className)}>
      <p className="field-label">{t("report.attachments.title")}</p>
      <ul className="panel mt-2" data-testid="attachment-list">
        {artifacts.data.map((artifact) => (
          <li key={artifact.artifact_id} className="row items-start">
            <span className="min-w-0">
              {artifact.source_url ? (
                <a
                  href={artifact.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="link block break-all font-mono text-[12.5px]"
                >
                  {artifact.source_url}
                </a>
              ) : (
                <span className="block font-mono text-[12.5px]">{artifact.filename}</span>
              )}
              {artifact.supported_claim ? (
                <p className="mt-0.5 text-[12.5px] text-muted-foreground">
                  {artifact.supported_claim}
                </p>
              ) : null}
              {artifact.extraction_state === "failed" && artifact.extraction_note ? (
                <p className="mt-0.5 text-[12.5px] text-bad">{artifact.extraction_note}</p>
              ) : null}
            </span>
            <span className="flex shrink-0 items-center gap-2.5">
              <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-faint">
                {t(`report.attachments.state.${artifact.extraction_state}`, {
                  defaultValue: artifact.extraction_state,
                })}
              </span>
              {/* A link has no stored bytes, so it gets no download — the address above is how
                  you open one, and it is already a link. */}
              {artifact.source_url ? null : (
                <button
                  type="button"
                  onClick={() => void openArtifact(artifact.artifact_id)}
                  className="btn-quiet"
                >
                  {t("report.attachments.download")}
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
