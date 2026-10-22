"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { Button, Field, Input } from "@/components/ui";
import { ApiError, api, errorMessage, get, post } from "@/lib/api";
import type { Me } from "@/lib/types";

function useAfterSignIn() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  return async () => {
    qc.setQueryData(["me"], undefined);
    await qc.invalidateQueries({ queryKey: ["me"] });
    const next = params.get("next");
    router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
  };
}

function SignInForm() {
  const afterSignIn = useAfterSignIn();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const me = await post<Omit<Me, "provider">>("/auth/login", { email, password });
      await afterSignIn();
      void me;
    } catch (err) {
      setError(err instanceof ApiError && err.code === "rate_limited" ? "Too many attempts. Wait a few minutes and try again." : errorMessage(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4" aria-describedby={error ? "login-error" : undefined}>
      <Field label="Email">
        <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className="h-10" />
      </Field>
      <Field label="Password">
        <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="h-10" />
      </Field>
      {error ? (
        <p id="login-error" role="alert" className="rounded-md bg-bad-soft px-3 py-2 text-[13px] text-bad">
          {error}
        </p>
      ) : null}
      <Button type="submit" variant="primary" size="md" loading={pending} className="w-full">
        Sign in
      </Button>
    </form>
  );
}

function CreateAdminForm() {
  const afterSignIn = useAfterSignIn();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password.length < 10) {
      setError("Use at least 10 characters for the password.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const me = await post<Omit<Me, "provider">>("/auth/setup", { name: name || undefined, email, password });
      await afterSignIn();
      void me;
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4" aria-describedby={error ? "setup-error" : undefined}>
      <p className="text-[13px] text-muted">
        First run — this creates the owner account for this instance. There is no other account yet.
      </p>
      <Field label="Your name">
        <Input type="text" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} className="h-10" placeholder="Optional" />
      </Field>
      <Field label="Email">
        <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className="h-10" />
      </Field>
      <Field label="Password" hint="At least 10 characters">
        <Input type="password" autoComplete="new-password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} className="h-10" />
      </Field>
      <Field label="Confirm password">
        <Input type="password" autoComplete="new-password" required minLength={10} value={confirm} onChange={(e) => setConfirm(e.target.value)} className="h-10" />
      </Field>
      {error ? (
        <p id="setup-error" role="alert" className="rounded-md bg-bad-soft px-3 py-2 text-[13px] text-bad">
          {error}
        </p>
      ) : null}
      <Button type="submit" variant="primary" size="md" loading={pending} className="w-full">
        Create account
      </Button>
    </form>
  );
}

function AuthForm() {
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    get<{ needs_setup: boolean }>("/auth/setup")
      .then((status) => {
        if (!cancelled) setNeedsSetup(status.needs_setup);
      })
      .catch(() => {
        if (!cancelled) setNeedsSetup(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (needsSetup === null) return <p className="py-8 text-center text-[13px] text-muted">Loading…</p>;
  return needsSetup ? <CreateAdminForm /> : <SignInForm />;
}

export default function LoginPage() {
  const router = useRouter();
  const qc = useQueryClient();

  // If auth is already available (a real session or DISABLE_AUTH=true on the API), skip the
  // login screen and go straight to the dashboard.
  useEffect(() => {
    api<Me>("/auth/me", { redirectOn401: false })
      .then((me) => {
        qc.setQueryData(["me"], me);
        router.replace("/");
      })
      .catch(() => {
        /* not signed in: show the form */
      });
  }, [qc, router]);

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <p className="font-display text-[30px] leading-tight font-semibold text-ink">The Executive Narrative</p>
          <p className="mt-1 text-[11px] tracking-[0.2em] text-muted uppercase">Editorial engine · Powered by LayerFlow</p>
        </div>
        <div className="rounded-lg border border-line bg-surface p-6 shadow-sm">
          <Suspense fallback={null}>
            <AuthForm />
          </Suspense>
        </div>
        <p className="mt-6 text-center text-xs text-muted">Nothing publishes without human approval.</p>
      </div>
    </div>
  );
}
