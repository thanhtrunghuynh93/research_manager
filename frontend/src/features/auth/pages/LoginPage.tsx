import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import { homeFor } from "@/app/home";
import { useLogin } from "@/features/auth/queries";

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    login.mutate({ email, password }, { onSuccess: (user) => navigate(homeFor(user.role)) });
  }

  // The API answers a wrong password and an unknown address identically; show what it said.
  const problem = login.error instanceof ApiError ? login.error.problem.detail : null;

  return (
    <section className="mx-auto max-w-sm animate-rise-in py-10">
      <h1 className="font-display text-[2.125rem] font-normal tracking-[-0.015em]">
        {t("auth.signIn")}
      </h1>
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
      <p className="stamp mt-4">
        Invitation and recovery links are issued by the professor&apos;s bootstrap.
      </p>
    </section>
  );
}
