import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";

import { api, ApiError } from "@/api/client";

type Consent = { client_name: string; scope: string; workspace_name: string };
type Decision = { redirect_to: string };

/**
 * ADR 0025: the page a connector sends a professor to. The query string is the OAuth request; it
 * is posted back unchanged and the API validates it, so nothing on this page is trusted by the
 * server. Allow and Deny both end in a redirect to the address the client registered.
 */
export function ConnectPage() {
  const { t } = useTranslation();
  const request = Object.fromEntries(new URLSearchParams(useLocation().search));

  const consent = useQuery({
    queryKey: ["oauth-consent", request],
    queryFn: () => api.post<Consent>("/api/v1/oauth/consent", request),
    retry: false,
  });
  const decide = useMutation({
    mutationFn: (verb: "authorize" | "deny") =>
      verb === "authorize"
        ? api.post<Decision>("/api/v1/oauth/authorize", request)
        : api.post<Decision>("/api/v1/oauth/deny", request),
    onSuccess: (decision) => window.location.assign(decision.redirect_to),
  });

  if (consent.isPending) return <p className="stamp">{t("common.loading")}</p>;
  if (consent.isError) {
    const detail = consent.error instanceof ApiError ? consent.error.problem.detail : "";
    return (
      <section className="mx-auto max-w-md py-10">
        <p role="alert" className="text-sm text-bad">
          {t("connect.invalid")} {detail}
        </p>
      </section>
    );
  }

  const failure = decide.error instanceof ApiError ? decide.error.problem.detail : null;
  return (
    <section className="mx-auto max-w-md animate-rise-in py-10">
      <h1 className="font-display text-figure font-normal tracking-[-0.015em]">
        {t("connect.title", { client: consent.data.client_name })}
      </h1>
      <div className="panel mt-6 space-y-3 p-5">
        <p>{t("connect.reads", { workspace: consent.data.workspace_name })}</p>
        <p className="text-ui text-muted-foreground">
          {consent.data.scope.split(" ").includes("rms:feedback")
            ? t("connect.feedback")
            : t("connect.readOnly")}
        </p>
        <p className="text-ui text-muted-foreground">{t("connect.revoke")}</p>
        {failure && (
          <p role="alert" className="text-sm text-bad">
            {failure}
          </p>
        )}
        <div className="flex gap-2.5 pt-2">
          <button
            type="button"
            className="btn-primary"
            disabled={decide.isPending}
            onClick={() => decide.mutate("authorize")}
          >
            {t("connect.allow")}
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={decide.isPending}
            onClick={() => decide.mutate("deny")}
          >
            {t("connect.deny")}
          </button>
        </div>
      </div>
    </section>
  );
}
