/**
 * The monthly ceiling on model spend, and what has gone against it (requirements §11).
 *
 * `PUT /admin/ai/budgets` has existed since the pipeline did and no screen called it, so a
 * deployment with a live key spent without a ceiling until somebody set one with curl — and
 * `implementation_status` §5 has been listing that as a decision owed by the professor ever since.
 * A limit nobody can set is not a limit.
 *
 * It lives beside the calendar for the same reason the calendar does: this is a workspace setting,
 * and one more screen for one more form is how a professor ends up with six places to look.
 *
 * No budget is not a budget of zero. Leaving the field empty means the work is never refused for
 * want of a number, which is deliberate (`cost.check_budget`) — so the panel says that outright
 * rather than letting an empty box read as "nothing may be spent".
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Failure } from "@/components/Failure";
import { useAiBudgets, useSetAiBudget, useAiUsage } from "@/features/workspaces/queries";

export function AiBudgetPanel() {
  const { t } = useTranslation();
  const budgets = useAiBudgets();
  const usage = useAiUsage();
  const save = useSetAiBudget();
  const [limit, setLimit] = useState<string | null>(null);

  if (budgets.isPending) return null;
  if (budgets.isError)
    return (
      <section className="panel mt-8 max-w-2xl p-4">
        <h2 className="section-title">{t("budget.title")}</h2>
        <p className="mt-2">
          <Failure error={budgets.error} />
        </p>
      </section>
    );

  const current = budgets.data;
  const value = limit ?? current.monthly_usd ?? "";

  return (
    <section className="panel mt-8 max-w-2xl p-4" data-testid="budget-panel">
      <h2 className="section-title">{t("budget.title")}</h2>
      <p className="stamp mt-1">{t("budget.intro")}</p>

      <p className="mt-3 text-sm" data-testid="budget-state">
        {current.monthly_usd
          ? t("budget.configured", { spent: current.spent_usd, limit: current.monthly_usd })
          : t("budget.none", { spent: current.spent_usd })}
      </p>
      {current.reason ? (
        <p className="mt-1 text-ui text-warn" data-testid="budget-reason">
          {current.reason}
        </p>
      ) : null}
      {usage.data ? (
        <p className="stamp mt-1" data-testid="budget-usage">
          {t("budget.usage", {
            calls: usage.data.calls,
            failed: usage.data.failed,
            cost: usage.data.cost_usd,
          })}
        </p>
      ) : null}

      <form
        className="mt-4 flex flex-wrap items-end gap-4 border-t border-border pt-4"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate({
            // An empty box is "no ceiling", not zero — and zero is a real setting that stops
            // every analysis, so the two must not collapse into each other.
            monthly_usd: value.trim() === "" ? null : value.trim(),
            project_monthly_usd: current.project_monthly_usd ?? {},
          });
        }}
      >
        <label className="block min-w-[12rem] flex-1">
          <span className="field-label">{t("budget.monthly")}</span>
          <input
            type="number"
            min={0}
            step="0.01"
            value={value}
            placeholder={t("budget.placeholder")}
            onChange={(event) => setLimit(event.target.value)}
            className="input font-mono"
          />
        </label>
        <button type="submit" disabled={save.isPending} className="btn-ghost">
          {t("budget.save")}
        </button>
        {save.isSuccess ? (
          <span className="stamp" role="status">
            {t("budget.saved")}
          </span>
        ) : null}
        <Failure error={save.error} />
      </form>
      <p className="stamp mt-3">{t("budget.note")}</p>
    </section>
  );
}
