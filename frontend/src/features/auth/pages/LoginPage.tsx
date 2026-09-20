import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import { homeFor } from "@/app/home";
import { useLogin, useRequestPasswordReset } from "@/features/auth/queries";

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [recovering, setRecovering] = useState(false);
  // Set by the reset page on its way here, so the person is told the change took effect.
  const justReset = (location.state as { reset?: boolean } | null)?.reset === true;

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    login.mutate({ email, password }, { onSuccess: (user) => navigate(homeFor(user.role)) });
  }

  // The API answers a wrong password and an unknown address identically; show what it said.
  const problem = login.error instanceof ApiError ? login.error.problem.detail : null;

  return (
    <section className="mx-auto max-w-sm animate-rise-in py-10">
      <h1 className="font-display text-figure font-normal tracking-[-0.015em]">
        {t("auth.signIn")}
      </h1>
      {justReset && (
        <p role="status" className="notice-warn mt-6">
          {t("reset.done")}
        </p>
      )}
      <form className="panel mt-6 space-y-4 p-5" onSubmit={onSubmit}>
        <div>
          <label className="field-label" htmlFor="email">
            {t("auth.email")}
          </label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="input bg-raised"
          />
        </div>
        <div>
          <label className="field-label" htmlFor="password">
            {t("auth.password")}
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="input bg-raised"
          />
        </div>
        {problem && (
          <p role="alert" className="text-sm text-bad">
            {problem}
          </p>
        )}
        <button type="submit" disabled={login.isPending} className="btn-primary w-full">
          {login.isPending ? t("common.loading") : t("auth.signIn")}
        </button>
      </form>
      <div className="mt-4">
        {recovering ? (
          <RecoveryRequest email={email} />
        ) : (
          <button type="button" onClick={() => setRecovering(true)} className="btn-quiet">
            {t("reset.forgot")}
          </button>
        )}
      </div>
      <p className="stamp mt-4">{t("auth.invitedNote")}</p>
    </section>
  );
}

/**
 * AUTH-01: ask for a recovery link.
 *
 * The confirmation is the same sentence whether or not the address has an account, because the
 * API answers the same way for both — a screen that said "no such account" would undo the
 * property the endpoint exists to protect.
 */
function RecoveryRequest({ email: initial }: { email: string }) {
  const { t } = useTranslation();
  const [email, setEmail] = useState(initial);
  const request = useRequestPasswordReset();

  if (request.isSuccess) {
    return (
      <p role="status" className="text-ui text-muted-foreground">
        {t("reset.requested")}
      </p>
    );
  }

  return (
    <form
      className="flex flex-wrap items-end gap-2.5"
      onSubmit={(event) => {
        event.preventDefault();
        request.mutate({ email });
      }}
    >
      <label className="block flex-1">
        <span className="field-label" id="recovery-label">
          {t("reset.recoveryAddress")}
        </span>
        <input
          type="email"
          required
          aria-labelledby="recovery-label"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="input bg-raised"
        />
      </label>
      <button type="submit" disabled={request.isPending} className="btn-ghost">
        {t("reset.sendLink")}
      </button>
    </form>
  );
}
