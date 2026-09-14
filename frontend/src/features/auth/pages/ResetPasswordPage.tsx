/**
 * AUTH-01: the page a recovery link lands on, for every user and for break-glass alike.
 *
 * Shaped like the invitation page and deliberately not merged with it: accepting an invitation
 * starts a session because the token proves control of the invited mailbox and the person is
 * plainly here; a reset may have been requested from another device, or by an operator handing a
 * break-glass link over the phone. So this one ends at the sign-in form rather than inside the app.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { useResetPassword } from "@/features/auth/queries";

/** Mirrors PASSWORD_MIN_LENGTH in the API, so the rule is stated before the round trip. */
const PASSWORD_MIN_LENGTH = 12;

export function ResetPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token");
  const reset = useResetPassword();

  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");

  const mismatch = confirmation.length > 0 && password !== confirmation;
  const problem = reset.error instanceof ApiError ? reset.error.problem.detail : null;

  if (!token) {
    return (
      <section className="mx-auto max-w-sm animate-rise-in py-10">
        <h1 className="font-display text-[2.125rem] font-normal tracking-[-0.015em]">
          {t("reset.title")}
        </h1>
        <p role="alert" className="notice-warn mt-6">
          {t("reset.noToken")}
        </p>
        <p className="mt-4">
          <Link to="/login">{t("auth.signIn")}</Link>
        </p>
      </section>
    );
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (mismatch) return;
    reset.mutate(
      { token: token!, password },
      { onSuccess: () => navigate("/login", { replace: true, state: { reset: true } }) },
    );
  }

  return (
    <section className="mx-auto max-w-sm animate-rise-in py-10">
      <h1 className="font-display text-[2.125rem] font-normal tracking-[-0.015em]">
        {t("reset.title")}
      </h1>
      <p className="mt-2 text-[13.5px] text-muted-foreground">{t("reset.intro")}</p>

      <form className="panel mt-6 space-y-4 p-5" onSubmit={onSubmit}>
        <div>
          <label className="field-label" htmlFor="password">
            {t("reset.password")}
          </label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={PASSWORD_MIN_LENGTH}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="input bg-raised"
          />
          <p className="stamp mt-1.5">{t("accept.rule", { count: PASSWORD_MIN_LENGTH })}</p>
        </div>
        <div>
          <label className="field-label" htmlFor="confirmation">
            {t("accept.confirm")}
          </label>
          <input
            id="confirmation"
            type="password"
            autoComplete="new-password"
            required
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            className="input bg-raised"
          />
        </div>
        {mismatch && (
          <p role="alert" className="text-sm text-bad">
            {t("accept.mismatch")}
          </p>
        )}
        {problem && (
          <p role="alert" className="text-sm text-bad">
            {problem}
          </p>
        )}
        <button type="submit" disabled={reset.isPending || mismatch} className="btn-primary w-full">
          {reset.isPending ? t("common.loading") : t("reset.submit")}
        </button>
      </form>
    </section>
  );
}
