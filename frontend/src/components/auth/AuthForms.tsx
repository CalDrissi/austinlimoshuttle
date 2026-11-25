"use client";

/**
 * Shared sign-in / create-account forms.
 *
 * One source of truth for the auth logic (password + email-code sign-in,
 * registration incl. the neutral 202 path) used by BOTH the standalone
 * /login and /register pages and the in-flow AuthModal on the booking pages.
 * Presentation is kept to the flow's form language; the host supplies the
 * wrapper (page section or dialog) and decides what happens on success.
 */

import { useState } from "react";
import { notify } from "@/lib/feedback";
import { API_BASE_URL } from "@/lib/api/config";
import { ApiRequestError } from "@/lib/api/client";
import { authService } from "@/lib/api/auth.service";
import { useRefreshAuth } from "@/hooks/useAuth";

export function LoginFields({ onSuccess, idPrefix = "login" }: {
  onSuccess: () => void;
  idPrefix?: string;
}) {
  const refreshAuth = useRefreshAuth();
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
        setNotice("Code sent — check your inbox."); return;
      }
      const signedIn = method === "password"
        ? await authService.login({ email: email.trim(), password })
        : await authService.verifyCode({ email: email.trim(), code });
      notify(`Welcome back, ${signedIn.first_name || "traveler"}`);
      await refreshAuth();
      onSuccess();
    } catch (err) {
      setError(method === "password"
        ? "Email or password is incorrect"
        : codeSent && err instanceof ApiRequestError && err.status === 400
          ? "That code is invalid or has expired."
          : "Unable to " + (codeSent ? "sign in" : "send a code") + ". Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="mm-signin-form" onSubmit={submit}>
      <div className="mb-20">
        <label htmlFor={`${idPrefix}-email`} className="text-14 color-grey">Email</label>
        <input id={`${idPrefix}-email`} autoComplete="email" placeholder="you@example.com" type="email" className="form-control" required disabled={busy} value={email}
          onChange={(e) => { setEmail(e.target.value); setCodeSent(false); setNotice(""); setCode(""); }} />
      </div>
      {method === "password" && <div className="mb-10">
        <label htmlFor={`${idPrefix}-password`} className="text-14 color-grey">Password</label>
        <input id={`${idPrefix}-password`} autoComplete="current-password" placeholder="Your password" type="password" className="form-control" required disabled={busy} value={password}
          onChange={(e) => setPassword(e.target.value)} />
      </div>}
      {method === "code" && codeSent && <div className="mb-20"><label htmlFor={`${idPrefix}-code`}>6-digit email code</label><input id={`${idPrefix}-code`} className="form-control" autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required disabled={busy} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} /></div>}
      {method === "password" && <p className="text-13 mb-20"><a className="mm-password-reset" href={`${API_BASE_URL.replace(/\/api\/?$/, "")}/accounts/password-reset/`}>Forgot password?</a></p>}
      {notice && <p role="status" className="mm-feedback">{notice}</p>}
      {error && <p role="alert" className="text-14 mb-15" style={{ color: "#c0392b" }}>{error}</p>}
      <button className="btn btn-primary hover-up w-100" type="submit" disabled={busy}>
        {busy ? (method === "code" && !codeSent ? "Sending code…" : "Signing in…") : method === "code" && !codeSent ? "Send email code" : method === "code" ? "Sign in with code" : "Sign in"}
      </button>
      <button type="button" className="btn btn-border w-100 mt-15" disabled={busy} onClick={() => { setMethod(method === "password" ? "code" : "password"); setError(""); setNotice(""); setCodeSent(false); setCode(""); }}>{method === "password" ? "Email me a sign-in code instead" : "Use password instead"}</button>
      {method === "code" && codeSent && <button type="button" className="btn btn-border w-100 mt-10" disabled={busy} onClick={() => { setCodeSent(false); setCode(""); setNotice(""); }}>Request a new code</button>}
    </form>
  );
}

export function RegisterFields({ onSuccess, initialEmail = "", idPrefix = "register" }: {
  onSuccess: () => void;
  initialEmail?: string;
  idPrefix?: string;
}) {
  const refreshAuth = useRefreshAuth();
  const [form, setForm] = useState({ first_name: "", last_name: "", email: initialEmail, phone: "", password: "" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      const result = (await authService.register({
        email: form.email.trim(),
        password: form.password,
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        phone: form.phone.trim(),
      })) as unknown as { email?: string; detail?: string };

      // 201 returns the new User (and signs them in); 202 is the neutral
      // "if that address can be registered…" response for an existing email.
      if (result?.email) {
        notify("Account created — welcome!");
        await refreshAuth();
        onSuccess();
      } else {
        setNotice("If that address can be registered, you'll receive an email.");
        setBusy(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed.");
      setBusy(false);
    }
  };

  return (
    <form className="mm-signin-form" onSubmit={submit}>
      <div className="row">
        <div className="col-6 mb-20">
          <label htmlFor={`${idPrefix}-first-name`} className="text-14 color-grey">First name</label>
          <input id={`${idPrefix}-first-name`} autoComplete="given-name" className="form-control" value={form.first_name} onChange={set("first_name")} />
        </div>
        <div className="col-6 mb-20">
          <label htmlFor={`${idPrefix}-last-name`} className="text-14 color-grey">Last name</label>
          <input id={`${idPrefix}-last-name`} autoComplete="family-name" className="form-control" value={form.last_name} onChange={set("last_name")} />
        </div>
      </div>
      <div className="mb-20">
        <label htmlFor={`${idPrefix}-email`} className="text-14 color-grey">Email</label>
        <input id={`${idPrefix}-email`} autoComplete="email" type="email" className="form-control" required value={form.email} onChange={set("email")} />
      </div>
      <div className="mb-20">
        <label htmlFor={`${idPrefix}-phone`} className="text-14 color-grey">Phone (optional)</label>
        <input id={`${idPrefix}-phone`} autoComplete="tel" type="tel" className="form-control" value={form.phone} onChange={set("phone")} />
      </div>
      <div className="mb-20">
        <label htmlFor={`${idPrefix}-password`} className="text-14 color-grey">Password</label>
        <input id={`${idPrefix}-password`} autoComplete="new-password" type="password" className="form-control" required value={form.password} onChange={set("password")} />
        <span className="text-13 color-grey">At least 10 characters.</span>
      </div>
      {error && <p className="text-14 mb-15" style={{ color: "#c0392b" }}>{error}</p>}
      {notice && <p className="text-14 mb-15" style={{ color: "#1e7e34" }}>{notice}</p>}
      <button className="btn btn-primary hover-up w-100" type="submit" disabled={busy}>
        {busy ? "Creating…" : "Create account"}
      </button>
    </form>
  );
}
