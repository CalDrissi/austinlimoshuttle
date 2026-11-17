"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { clientDestination, notify } from "@/lib/feedback";
import { authService } from "@/lib/api/auth.service";
import { useRefreshAuth } from "@/hooks/useAuth";

function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const refreshAuth = useRefreshAuth();
  const next = clientDestination(params.get("next"));

  const [form, setForm] = useState({ first_name: "", last_name: "", email: params.get("email") || "", phone: "", password: "" });
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
        notify("Your account is ready — welcome!");
        await refreshAuth();
        router.push(next);
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
    <section className="section pt-80 pb-80">
      <div className="container" style={{ maxWidth: 460 }}>
        <h2 className="heading-36-medium mb-10">Create your account</h2>
        <p className="text-14 color-grey mb-30">
          Already have one? <Link href={`/login?next=${encodeURIComponent(next)}`}>Sign in</Link>
        </p>
        <form className="mm-signin-form" onSubmit={submit}>
          <div className="row">
            <div className="col-6 mb-20">
              <label className="text-14 color-grey">First name</label>
              <input className="form-control" value={form.first_name} onChange={set("first_name")} />
            </div>
            <div className="col-6 mb-20">
              <label className="text-14 color-grey">Last name</label>
              <input className="form-control" value={form.last_name} onChange={set("last_name")} />
            </div>
          </div>
          <div className="mb-20">
            <label className="text-14 color-grey">Email</label>
            <input type="email" className="form-control" required value={form.email} onChange={set("email")} />
          </div>
          <div className="mb-20">
            <label className="text-14 color-grey">Phone (optional)</label>
            <input className="form-control" value={form.phone} onChange={set("phone")} />
          </div>
          <div className="mb-20">
            <label className="text-14 color-grey">Password</label>
            <input type="password" className="form-control" required value={form.password} onChange={set("password")} />
            <span className="text-13 color-grey">At least 10 characters.</span>
          </div>
          {error && <p className="text-14 mb-15" style={{ color: "#c0392b" }}>{error}</p>}
          {notice && <p className="text-14 mb-15" style={{ color: "#1e7e34" }}>{notice}</p>}
          <button className="btn btn-primary hover-up w-100" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create account"}
          </button>
        </form>
      </div>
    </section>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterForm />
    </Suspense>
  );
}
