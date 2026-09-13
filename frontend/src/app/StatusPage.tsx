import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";

type Readiness = {
  status: "ready" | "degraded";
  checks: Record<string, "ok" | "fail" | "skipped">;
};

export function StatusPage() {
  const { t } = useTranslation();
  const readiness = useQuery({
    queryKey: ["readyz"],
    queryFn: () => api.get<Readiness>("/api/readyz", { acceptStatuses: [200, 503] }),
    refetchInterval: 15_000,
  });

  return (
    <section className="max-w-xl animate-rise-in space-y-5">
      <div>
        <h1 className="page-title">{t("status.title")}</h1>
        <p className="stamp mt-2">Polled every 15 s · /api/readyz</p>
      </div>
      {readiness.isPending && <p className="stamp">{t("common.loading")}</p>}
      {readiness.isError && <p className="text-sm text-bad">{t("status.unreachable")}</p>}
      {readiness.data && (
        <ul className="panel">
          {Object.entries(readiness.data.checks).map(([name, state]) => (
            <li key={name} className="row font-mono text-[13px]">
              <span>{name}</span>
              <span
                className={
                  state === "ok" ? "text-good" : state === "fail" ? "text-warn" : "text-faint"
                }
              >
                {state}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
