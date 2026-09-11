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
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">{t("status.title")}</h1>
      {readiness.isPending && <p className="text-muted-foreground">{t("common.loading")}</p>}
      {readiness.isError && <p className="text-red-600">{t("status.unreachable")}</p>}
      {readiness.data && (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {Object.entries(readiness.data.checks).map(([name, state]) => (
            <li key={name} className="flex items-center justify-between px-4 py-2 text-sm">
              <span>{name}</span>
              <span className={state === "ok" ? "text-green-600" : "text-amber-600"}>{state}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
