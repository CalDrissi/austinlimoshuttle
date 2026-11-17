"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { clientDestination, notify } from "@/lib/feedback";
import { API_BASE_URL } from "@/lib/api/config";
import { authService } from "@/lib/api/auth.service";
import { useRefreshAuth } from "@/hooks/useAuth";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const refreshAuth = useRefreshAuth();
  const next = clientDestination(params.get("next"));

  const [email, setEmail] = useState("");
  const [method, setMethod] = useState<"password" | "code">("password");
  const [codeSent, setCodeSent] = useState(false);
  const [code, setCode] = useState("");
  const [notice, setNotice] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (method === "code" && !codeSent) {
        await authService.sendCode(email.trim()); setCodeSent(true);
        setNotice("Code sent — check your inbox."); setBusy(false); return;
      }
      const signedIn = method === "password"
        ? await authService.login({ email: email.trim(), password })
        : await authService.verifyCode({ email: email.trim(), code });
      notify(`Welcome back, ${signedIn.first_name || "traveler"}`);
      await refreshAuth();
      router.push(next);
    } catch (err) {
      setError(method === "password" ? "Email or password is incorrect" : "That code is invalid or has expired. Please try again.");
      setBusy(false);
    }
  };

  return (
    <section className="section pt-80 pb-80">
      <div className="container" style={{ maxWidth: 440 }}>
        <h2 className="heading-36-medium mb-10">Sign in</h2>
        <p className="text-14 color-grey mb-30">
          New here? <Link href={`/register?next=${encodeURIComponent(next)}`}>Create an account</Link>
        </p>
        <form className="mm-signin-form" onSubmit={submit}>
          <div className="mb-20">
            <label htmlFor="login-email" className="text-14 color-grey">Email</label>
            <input id="login-email" autoComplete="email" placeholder="you@example.com" type="email" className="form-control" required value={email}
              onChange={(e) => { setEmail(e.target.value); setCodeSent(false); setNotice(""); setCode(""); }} />
          </div>
          {method === "password" && <div className="mb-10">
            <label htmlFor="login-password" className="text-14 color-grey">Password</label>
            <input id="login-password" autoComplete="current-password" placeholder="Your password" type="password" className="form-control" required value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </div>}
          {method === "code" && codeSent && <div className="mb-20"><label htmlFor="login-code">6-digit email code</label><input id="login-code" className="form-control" autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} /></div>}
          <p className="text-13 mb-20"><a href={`${API_BASE_URL.replace(/\/api\/?$/, "")}/accounts/password-reset/`}>Forgot password?</a></p>
          {notice && <p role="status" className="mm-feedback">{notice}</p>}
          {error && <p role="alert" className="text-14 mb-15" style={{ color: "#c0392b" }}>{error}</p>}
          <button className="btn btn-primary hover-up w-100" type="submit" disabled={busy}>
            {busy ? (method === "code" && !codeSent ? "Sending code…" : "Signing in…") : method === "code" && !codeSent ? "Send email code" : "Sign in"}
          </button>
          <button type="button" className="btn btn-border w-100 mt-15" disabled={busy} onClick={() => { setMethod(method === "password" ? "code" : "password"); setError(""); setNotice(""); setCodeSent(false); }}>{method === "password" ? "Email me a code instead" : "Use password instead"}</button>
          {method === "code" && codeSent && <button type="button" className="btn btn-border w-100 mt-10" disabled={busy} onClick={() => { setCodeSent(false); setCode(""); setNotice(""); }}>Request a new code</button>}
        </form>

        {next.startsWith("/booking") && (
          <>
            <div className="text-14 color-grey" style={{ textAlign: "center", margin: "18px 0" }}>— or —</div>
            <button className="btn btn-white hover-up w-100" type="button" onClick={() => router.push(next)}>
              Continue as guest
            </button>
            <p className="text-13 color-grey mt-10" style={{ textAlign: "center" }}>
              No account needed — you&apos;ll get a receipt by email.
            </p>
          </>
        )}
      </div>
    </section>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
