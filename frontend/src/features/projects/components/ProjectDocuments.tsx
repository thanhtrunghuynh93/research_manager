/**
 * PROJ-01: the documents that support the project itself — a protocol, a dataset description, the
 * paper being replicated.
 *
 * These are not a week's evidence and do not behave like it (ADR 0018). A file attached here
 * carries no period and no entry, and that is exactly what makes it the project's: everyone on the
 * project can read it, where a report attachment stays with its author and the professor. The one
 * who attached a file may take it back; a professor may read every one and remove none, which is
 * the rule report evidence already has.
 *
 * Nothing reads these files. They are not extracted, not indexed, and cannot be cited by an
 * assessment or the assistant, so the badge stays at "Uploaded" — which is what has happened.
 * Making them citable is a decision about what the model may read, and a larger one than this.
 *
 * The upload is the same three steps as everywhere else, from `@/lib/upload`: hash here, PUT
 * straight to the store, then ask the server to confirm against the checksum.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "@/api/client";
import { useSession } from "@/features/auth/queries";
import {
  attachProjectDocument,
  useProjectDocuments,
  useRefreshProjectDocuments,
} from "@/features/projects/queries";
import { type Sending } from "@/lib/upload";

/** Bytes, in the unit a person reading a file list wants — no decimals below a megabyte. */
function size(bytes: number): string {
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  if (bytes >= 1_000) return `${Math.round(bytes / 1_000)} KB`;
  return `${bytes} B`;
}

export function ProjectDocuments({
  projectId,
  canAttach,
}: {
  projectId: string;
  /** A member or a professor. A student who has left keeps the record and loses the documents. */
  canAttach: boolean;
}) {
  const { t } = useTranslation();
  const session = useSession();
  const documents = useProjectDocuments(projectId);
  const refresh = useRefreshProjectDocuments(projectId);
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState<Sending | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      await attachProjectDocument(projectId, file, setSending);
      refresh();
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.problem.detail : String(problem));
    } finally {
      setBusy(false);
      setSending(null);
    }
  }

  async function remove(artifactId: string, name: string) {
    if (!window.confirm(t("project.documents.removeConfirm", { name }))) return;
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/api/v1/artifacts/${artifactId}`);
      refresh();
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.problem.detail : String(problem));
    } finally {
      setBusy(false);
    }
  }

  async function open(artifactId: string) {
    try {
      const grant = await api.get<{ url: string }>(`/api/v1/artifacts/${artifactId}/download`);
      window.location.assign(grant.url);
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.problem.detail : String(problem));
    }
  }

  return (
    <section data-testid="project-documents">
      <h2 className="section-title mb-2.5">{t("project.documents.title")}</h2>
      <ul className="panel">
        {documents.data?.map((document) => (
          <li key={document.artifact_id} className="row items-start">
            <div className="min-w-0">
              <span className="block break-all font-mono text-note">{document.filename}</span>
              <span className="stamp">{size(document.byte_size)}</span>
            </div>
            <span className="flex items-center gap-2.5">
              <button
                type="button"
                onClick={() => void open(document.artifact_id)}
                className="btn-quiet"
              >
                {t("project.documents.download")}
              </button>
              {/* Only the person who attached it: the API refuses anyone else, professor
                  included, so offering the button to them would be offering a refusal. */}
              {document.owner_student_id === session.data?.id && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void remove(document.artifact_id, document.filename)}
                  className="btn-quiet"
                  data-testid="remove-document"
                >
                  {t("project.documents.remove")}
                </button>
              )}
            </span>
          </li>
        ))}
        {documents.data?.length === 0 && (
          <li className="px-4 py-2.5 text-sm text-muted-foreground">
            {t("project.documents.none")}
          </li>
        )}
      </ul>

      {canAttach && (
        <div className="mt-3">
          <label className="btn-quiet inline-block cursor-pointer">
            <input
              type="file"
              className="sr-only"
              disabled={busy}
              onChange={(event) => {
                const file = event.target.files?.[0];
                // Cleared before the upload so choosing the same file twice fires a change event.
                event.target.value = "";
                if (file) void upload(file);
              }}
            />
            {t("project.documents.attach")}
          </label>
          <p className="stamp mt-1.5">{t("project.documents.limit")}</p>
        </div>
      )}

      {sending && (
        <p className="stamp mt-2" role="status" data-testid="document-sending">
          {t(`project.documents.stage.${sending.stage}`, { name: sending.name })}
          {sending.fraction === null ? "" : ` ${Math.round(sending.fraction * 100)}%`}
        </p>
      )}
      {error && (
        <p className="mt-2 text-sm text-bad" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
