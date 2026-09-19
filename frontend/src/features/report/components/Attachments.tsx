/**
 * REP-04: attaching evidence to a project entry.
 *
 * The file never passes through the API. The client hashes it, asks for permission to write one
 * key, PUTs the bytes straight to object storage, and then asks the server to confirm — which is
 * when the server checks the checksum. Three steps rather than one, because the middle one is the
 * part that must not go through this application.
 *
 * The text is read when the week is submitted, not as each file arrives, so a version attached and
 * not yet submitted sits at `pending`. The badge says so in those words: it used to read "Reading…"
 * over a file nothing was reading, which looked like a job that had hung.
 *
 * The extraction state is shown rather than hidden. A PDF the server could not read is not the
 * same as a PDF with nothing in it, and the student is the person best placed to fix it.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "@/api/client";
import { Badge } from "@/components/evidence/Badges";
import { openArtifact } from "@/features/report/queries";

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
  truncated?: boolean;
  /** Where a linked artifact points. A file has none, and that is how the two are told apart. */
  source_url?: string | null;
  /** What the student said this shows. Recorded on attach, and shown back on the row. */
  supported_claim?: string;
};

/**
 * Whether this is a link we would even try to fetch, checked before anything is created.
 *
 * The server records a refused link rather than rejecting it, deliberately — REPO-08: the record
 * should say what the student pointed at and why we did not follow it. That is the right answer
 * for a link that resolves somewhere we will not go, and the wrong one for a typo: `not a url`
 * used to become a permanent attachment badged COULD NOT BE READ. A scheme this side of the
 * request keeps the typo out and leaves the deliberate refusals to the server.
 */
function fetchableLink(value: string): boolean {
  try {
    const { protocol } = new URL(value.trim());
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

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
  /** Called after anything is attached, so the caller can refetch the list from the server. */
  onAttached: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  // What is in flight, purely so the screen can say so. The file input cannot hold it: its value
  // is cleared on selection (see the change handler), and a disabled input showing nothing for the
  // several seconds this takes is indistinguishable from a broken one.
  const [sending, setSending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [claim, setClaim] = useState("");
  const [link, setLink] = useState("");

  async function upload(file: File) {
    setBusy(true);
    setSending(file.name);
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

      await api.post<Attachment>(`/api/v1/artifacts/${grant.artifact_id}/confirm`);
      onAttached();
      setClaim("");
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.problem.detail : String(problem));
    } finally {
      setBusy(false);
      setSending(null);
    }
  }

  async function remove(artifactId: string, filename: string) {
    if (!window.confirm(t("report.attachments.removeConfirm", { name: filename }))) return;
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/api/v1/artifacts/${artifactId}`);
      onAttached();
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.problem.detail : String(problem));
    } finally {
      setBusy(false);
    }
  }

  async function attachLink() {
    if (!link.trim()) return;
    if (!fetchableLink(link)) {
      setError(t("report.attachments.linkInvalid"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post<Attachment>("/api/v1/artifacts/links", {
        project_id: projectId,
        period_id: periodId,
        url: link,
        supported_claim: claim,
      });
      onAttached();
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
            <div className="min-w-0">
              {/* A link's filename is derived from its path, so two links to different sites can
                  both read "link". The address is the only thing that identifies one. */}
              {attachment.source_url ? (
                <a
                  href={attachment.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="link block break-all font-mono text-[12.5px]"
                >
                  {attachment.source_url}
                </a>
              ) : (
                <span className="block font-mono text-[12.5px]">{attachment.filename}</span>
              )}
              {/* The claim was written into a box labelled "What does this show?" and then never
                  shown again, so nobody could check it, correct it, or notice it was empty. */}
              {attachment.supported_claim ? (
                <p className="mt-0.5 text-[12.5px] text-muted-foreground" data-testid="claim">
                  {attachment.supported_claim}
                </p>
              ) : null}
              {/* Why a file or link could not be read, as text. It was the badge's `title`, which
                  a phone has no way to show and a screen reader does not announce as content. */}
              {attachment.extraction_state === "failed" && attachment.extraction_note ? (
                <p className="mt-0.5 text-[12.5px] text-bad" data-testid="extraction-note">
                  {attachment.extraction_note}
                </p>
              ) : null}
            </div>
            <span className="flex items-center gap-2.5">
              <ExtractionBadge attachment={attachment} />
              {/* A link has no stored bytes, so this asked for a download that 404s and threw
                  into the console with nothing on screen. The address above is the way to open
                  one, and it is already a link. */}
              {attachment.source_url ? null : (
                <button
                  type="button"
                  onClick={() => {
                    void openArtifact(attachment.artifact_id).catch((problem: unknown) =>
                      setError(
                        problem instanceof ApiError ? problem.problem.detail : String(problem),
                      ),
                    );
                  }}
                  className="btn-quiet"
                >
                  {t("report.attachments.download")}
                </button>
              )}
              <button
                type="button"
                disabled={busy}
                onClick={() => void remove(attachment.artifact_id, attachment.filename)}
                className="btn-quiet"
                data-testid="remove-attachment"
              >
                {t("report.attachments.remove")}
              </button>
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
              aria-busy={busy}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
                // Cleared so that choosing the same file again still fires a change — after a
                // failure that is exactly what someone does. The name is shown below instead.
                event.target.value = "";
              }}
              className="file-input"
            />
          </label>
          {sending && (
            <p className="stamp" role="status" data-testid="attachment-sending">
              {t("report.attachments.sending", { name: sending })}
            </p>
          )}
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
