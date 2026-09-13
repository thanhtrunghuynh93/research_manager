/**
 * REP-04: attaching evidence to a project entry.
 *
 * The file never passes through the API. The client hashes it, asks for permission to write one
 * key, PUTs the bytes straight to object storage, and then asks the server to confirm — which is
 * when the server checks the checksum and reads the text. Three steps rather than one, because the
 * middle one is the part that must not go through this application.
 *
 * The extraction state is shown rather than hidden. A PDF the server could not read is not the
 * same as a PDF with nothing in it, and the student is the person best placed to fix it.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "@/api/client";
import { Badge } from "@/components/evidence/Badges";

type Grant = {
  artifact_id: string;
  version_no: number;
  url: string;
  expires_in: number;
  headers: Record<string, string>;
};

export type Attachment = {
  artifact_id: string;
  version_no: number;
  filename: string;
  byte_size: number;
  extraction_state: "pending" | "ok" | "failed" | "unsupported";
  extraction_note: string;
  truncated: boolean;
};

/** The browser's own SHA-256, so the server has something to verify the upload against. */
async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function Attachments({
  projectId,
  periodId,
  attachments,
  onAttached,
}: {
  projectId: string;
  periodId: string;
  attachments: Attachment[];
  onAttached: (attachment: Attachment) => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [claim, setClaim] = useState("");
  const [link, setLink] = useState("");

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      const grant = await api.post<Grant>("/api/v1/artifacts/uploads", {
        project_id: projectId,
        period_id: periodId,
        filename: file.name,
        byte_size: file.size,
        sha256: await sha256(file),
        supported_claim: claim,
      });

      const response = await fetch(grant.url, {
        method: "PUT",
        headers: grant.headers,
        body: file,
      });
      if (!response.ok) throw new Error(`upload failed with ${response.status}`);

      const attached = await api.post<Attachment>(`/api/v1/artifacts/${grant.artifact_id}/confirm`);
      onAttached(attached);
      setClaim("");
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.problem.detail : String(problem));
    } finally {
      setBusy(false);
    }
  }

  async function attachLink() {
    if (!link.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const attached = await api.post<Attachment>("/api/v1/artifacts/links", {
        project_id: projectId,
        period_id: periodId,
        url: link,
        supported_claim: claim,
      });
      onAttached(attached);
      setLink("");
      setClaim("");
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.problem.detail : String(problem));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-7 border-t border-border pt-5" data-testid="attachments">
      <h3 className="section-title">{t("report.attachments.title")}</h3>
      <p className="stamp mt-1.5">{t("report.attachments.limit")}</p>

      <ul className="panel mt-3.5" data-testid="attachment-list">
        {attachments.map((attachment) => (
          <li
            key={`${attachment.artifact_id}:${attachment.version_no}`}
            className="row items-start"
          >
            <span className="font-mono text-[12.5px]">{attachment.filename}</span>
            <span className="flex items-center gap-2.5">
              <ExtractionBadge attachment={attachment} />
              <a
                href={`/api/v1/artifacts/${attachment.artifact_id}/download`}
                className="btn-quiet"
              >
                {t("report.attachments.download")}
              </a>
            </span>
          </li>
        ))}
        {attachments.length === 0 && (
          <li className="px-4 py-2.5 text-sm text-muted-foreground">
            {t("report.attachments.none")}
          </li>
        )}
      </ul>

      <div className="mt-3.5 grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(240px,1fr))]">
        <label className="block">
          <span className="field-label">{t("report.attachments.claim")}</span>
          <input
            value={claim}
            onChange={(event) => setClaim(event.target.value)}
            placeholder={t("report.attachments.claimPlaceholder")}
            className="input"
          />
          <span className="stamp mt-1.5 block">{t("report.attachments.claimNote")}</span>
        </label>

        <div className="flex flex-col gap-2.5">
          <label className="block">
            <span className="field-label">{t("report.attachments.file")}</span>
            <input
              type="file"
              disabled={busy}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
                event.target.value = "";
              }}
              className="mt-2 w-full rounded border border-dashed border-border-strong bg-surface px-3 py-2.5 text-[13px] file:mr-3 file:rounded file:border file:border-border file:bg-raised file:px-2 file:py-1 file:text-[12px]"
            />
          </label>
          <label className="block">
            <span className="field-label">{t("report.attachments.link")}</span>
            <span className="mt-2 flex gap-2">
              <input
                value={link}
                onChange={(event) => setLink(event.target.value)}
                placeholder="https://…"
                className="min-w-0 flex-1 rounded border border-border-strong bg-surface px-3 py-2.5 text-sm"
              />
              <button
                type="button"
                disabled={busy}
                onClick={() => void attachLink()}
                className="btn-ghost whitespace-nowrap"
              >
                {t("report.attachments.addLink")}
              </button>
            </span>
          </label>
        </div>
      </div>

      {error && (
        <p role="alert" className="mt-3 text-sm text-bad" data-testid="attachment-error">
          {error}
        </p>
      )}
    </section>
  );
}

/** A file we could not read and a file with nothing to read are different, and read differently. */
function ExtractionBadge({ attachment }: { attachment: Attachment }) {
  const { t } = useTranslation();
  const tone =
    attachment.extraction_state === "ok"
      ? "good"
      : attachment.extraction_state === "failed"
        ? "bad"
        : "neutral";
  return (
    <Badge tone={tone} title={attachment.extraction_note} data-testid="extraction-badge">
      {t(`report.attachments.state.${attachment.extraction_state}`)}
      {attachment.truncated ? ` · ${t("report.attachments.truncated")}` : ""}
    </Badge>
  );
}
