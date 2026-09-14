/**
 * AUTH-01: the page an invitation link lands on — set a password, and the account is live.
 *
 * The token is the credential and it arrives in the query string, so it is never echoed back into
 * the page and never put in a field the person could edit. A link that carries none at all is a
 * mistyped or truncated URL rather than a form to fill in, and says so instead of failing on submit.
 *
 * Accepting starts the session server-side, so there is no second sign-in step: the new account
 * goes straight to the home that belongs to its role.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { homeFor } from "@/app/home";
import { useAcceptInvitation } from "@/features/auth/queries";

/** Mirrors PASSWORD_MIN_LENGTH in the API, so the rule is stated before the round trip. */
const PASSWORD_MIN_LENGTH = 12;

export function AcceptInvitationPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token");
  const accept = useAcceptInvitation();

  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [displayName, setDisplayName] = useState("");

  // Checked here rather than only by the API: a mistyped password the API accepts locks the
  // account out of the very link that would have fixed it.
  const mismatch = confirmation.length > 0 && password !== confirmation;
  const problem = accept.error instanceof ApiError ? accept.error.problem.detail : null;

  if (!token) {
    return (
      <section className="mx-auto max-w-sm animate-rise-in py-10">
        <h1 className="font-display text-[2.125rem] font-normal tracking-[-0.015em]">
          {t("accept.title")}
        </h1>
        <p role="alert" className="notice-warn mt-6">
          {t("accept.noToken")}
        </p>
      </section>
    );
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (mismatch) return;
    accept.mutate(
      { token: token!, password, display_name: displayName || undefined },
      { onSuccess: (user) => navigate(homeFor(user.role), { replace: true }) },
    );
  }

  return (
    <section className="mx-auto max-w-sm animate-rise-in py-10">
      <h1 className="font-display text-[2.125rem] font-normal tracking-[-0.015em]">
        {t("accept.title")}
      </h1>
      <p className="mt-2 text-[13.5px] text-muted-foreground">{t("accept.intro")}</p>

      <form className="panel mt-6 space-y-4 p-5" onSubmit={onSubmit}>
        <div>
          <label className="field-label" htmlFor="display-name">
            {t("accept.name")}
          </label>
          <input
            id="display-name"
            type="text"
            autoComplete="name"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            className="input bg-raised"
          />
        </div>
        <div>
          <label className="field-label" htmlFor="password">
            {t("accept.password")}
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
        <button
          type="submit"
          disabled={accept.isPending || mismatch}
          className="btn-primary w-full"
        >
          {accept.isPending ? t("common.loading") : t("accept.submit")}
        </button>
      </form>
      <p className="stamp mt-4">{t("accept.expiryNote")}</p>
    </section>
  );
}
