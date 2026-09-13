/**
 * UI-06: filtered exports, and a download that carries the caller's own authority.
 *
 * The page shows only the kinds this account may ask for, which the server answers rather than the
 * client assuming. The download link is a plain navigation to the API: the session cookie is the
 * credential, so there is no token to mint and nothing to leak into a URL.
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
    <section className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{t("exports.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("exports.scopeNote")}</p>
      </header>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">{t("exports.kinds")}</legend>
        {kinds.data?.kinds.map((kind) => (
          <label key={kind} className="flex items-center gap-2 text-sm">
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
            />
            {t(`exports.kind.${kind}`, { defaultValue: kind })}
          </label>
        ))}
      </fieldset>

      <div className="flex flex-wrap gap-4">
        <label className="space-y-1 text-sm">
          <span className="block font-medium">{t("exports.since")}</span>
          <input
            type="date"
            value={since}
            onChange={(event) => setSince(event.target.value)}
            className="rounded-md border border-border px-2 py-1"
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="block font-medium">{t("exports.until")}</span>
          <input
            type="date"
            value={until}
            onChange={(event) => setUntil(event.target.value)}
            className="rounded-md border border-border px-2 py-1"
          />
        </label>
      </div>

      <div className="flex flex-wrap gap-3">
        <a
          href={`/api/v1/exports?${params.toString()}`}
          download
          className="rounded-md border border-border px-3 py-1.5 text-sm font-medium"
          data-testid="download-json"
        >
          {t("exports.downloadJson")}
        </a>
        {chosen.map((kind) => (
          <a
            key={kind}
            href={`/api/v1/exports/${kind}.csv?${params.toString()}`}
            download
            className="rounded-md border border-border px-3 py-1.5 text-sm"
          >
            {t("exports.downloadCsv", { kind })}
          </a>
        ))}
      </div>

      <p className="text-xs text-muted-foreground">{t("exports.portabilityNote")}</p>
    </section>
  );
}
