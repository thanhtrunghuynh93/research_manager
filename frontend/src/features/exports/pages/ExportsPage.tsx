/**
 * UI-06: filtered exports, and a download that carries the caller's own authority.
 *
 * The page shows only the kinds this account may ask for, which the server answers rather than the
 * client assuming. The download link is a plain navigation to the API: the session cookie is the
 * credential, so there is no token to mint and nothing to leak into a URL. The request line is
 * printed under the buttons, because an export the reader cannot describe is one they cannot check.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { localDateToInstant } from "@/lib/dates";

type Kinds = { kinds: string[]; default: string[] };

export function ExportsPage() {
  const { t } = useTranslation();
  const kinds = useQuery({
    queryKey: ["exports", "kinds"],
    queryFn: () => api.get<Kinds>("/api/v1/exports/kinds"),
  });
  // null means "has not chosen", which is not the same as "chose nothing". Conflating them made
  // unticking the last box silently restore the server defaults, so the download carried kinds
  // the professor had just removed — and the boxes re-ticked themselves on screen.
  const [selected, setSelected] = useState<string[] | null>(null);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");

  const chosen = selected ?? kinds.data?.default ?? [];
  const params = new URLSearchParams();
  for (const kind of chosen) params.append("kinds", kind);
  // The inputs give a workspace-local calendar date; stamping it `Z` would read it as UTC and
  // move the window by the workspace's offset (UI-06).
  if (since) params.set("since", localDateToInstant(since, "start"));
  if (until) params.set("until", localDateToInstant(until, "end"));

  return (
    <section className="max-w-2xl animate-rise-in">
      <header>
        <h1 className="page-title">{t("exports.title")}</h1>
        <p className="mt-2 text-[13.5px] text-muted-foreground">{t("exports.scopeNote")}</p>
      </header>

      <fieldset className="panel mt-6 px-4 pb-4 pt-1.5">
        <legend className="field-label px-1.5">{t("exports.kinds")}</legend>
        {kinds.data?.kinds.map((kind) => (
          <label
            key={kind}
            className="flex cursor-pointer items-center gap-2.5 py-1.5 text-[13.5px]"
          >
            <input
              type="checkbox"
              checked={chosen.includes(kind)}
              onChange={(event) =>
                setSelected((previous) => {
                  const current = previous ?? chosen;
                  return event.target.checked
                    ? [...new Set([...current, kind])]
                    : current.filter((value) => value !== kind);
                })
              }
              className="h-4 w-4 accent-accent"
            />
            {t(`exports.kind.${kind}`, { defaultValue: kind })}
          </label>
        ))}
      </fieldset>

      <div className="mt-5 flex flex-wrap gap-4">
        <label className="block">
          <span className="field-label">{t("exports.since")}</span>
          <input
            type="date"
            value={since}
            onChange={(event) => setSince(event.target.value)}
            className="input w-auto font-mono"
          />
        </label>
        <label className="block">
          <span className="field-label">{t("exports.until")}</span>
          <input
            type="date"
            value={until}
            onChange={(event) => setUntil(event.target.value)}
            className="input w-auto font-mono"
          />
        </label>
      </div>

      <div className="mt-6 flex flex-wrap gap-2.5">
        <a
          href={`/api/v1/exports?${params.toString()}`}
          download
          className="btn-primary no-underline"
          data-testid="download-json"
        >
          {t("exports.downloadJson")}
        </a>
        {chosen.map((kind) => (
          <a
            key={kind}
            href={`/api/v1/exports/${kind}.csv?${params.toString()}`}
            download
            className="btn-ghost font-mono text-[12.5px] text-ink2 no-underline"
          >
            {t("exports.downloadCsv", { kind })}
          </a>
        ))}
      </div>

      <p className="stamp mt-5 break-all">GET /api/v1/exports?{params.toString()}</p>
      <p className="mt-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
        {t("exports.portabilityNote")}
      </p>
    </section>
  );
}
