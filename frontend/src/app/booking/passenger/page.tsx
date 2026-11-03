"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useBookingStore, useHydrated } from "@/lib/booking/store";
import { useAuth, useRefreshAuth } from "@/hooks/useAuth";
import { authService } from "@/lib/api/auth.service";
import { API_BASE_URL } from "@/lib/api/config";
import OrderSummary from "@/components/booking/OrderSummary";

type Panel = "signin" | "register" | null;

export default function BookingPassengerPage() {
  const router = useRouter();
  const { user, isLoading } = useAuth();
  const refreshAuth = useRefreshAuth();
  const quote = useBookingStore((s) => s.quote);
  const contact = useBookingStore((s) => s.contact);
  const setContact = useBookingStore((s) => s.setContact);
  const trip = useBookingStore((s) => s.trip);
  const setTrip = useBookingStore((s) => s.setTrip);
  const hydrated = useHydrated();

  const [name, setName] = useState(contact.name ?? "");
  const [email, setEmail] = useState(contact.email ?? "");
  const [phone, setPhone] = useState(contact.phone ?? "");
  const [forElse, setForElse] = useState(!!trip.forSomeoneElse);
  const [paxName, setPaxName] = useState(trip.passengerName ?? "");
  const [paxPhone, setPaxPhone] = useState(trip.passengerPhone ?? "");
  const [error, setError] = useState("");

  // Inline auth accordion
  const [panel, setPanel] = useState<Panel>(null);
  const [authBusy, setAuthBusy] = useState(false);
  const [authErr, setAuthErr] = useState("");
  const [authMsg, setAuthMsg] = useState("");
  const [li, setLi] = useState({ email: "", password: "" });
  const [reg, setReg] = useState({ first_name: "", last_name: "", email: "", password: "", phone: "" });

  useEffect(() => {
    if (hydrated && !quote) router.replace("/booking/vehicle");
  }, [hydrated, quote, router]);

  useEffect(() => {
    if (user) {
      setName((n) => n || `${user.first_name} ${user.last_name}`.trim());
      setEmail((e) => e || user.email);
      setPhone((p) => p || user.phone || "");
    }
  }, [user]);

  if (!hydrated || !quote) return null;

  const doLogin = async () => {
    setAuthBusy(true); setAuthErr(""); setAuthMsg("");
    try {
      await authService.login({ email: li.email.trim(), password: li.password });
      await refreshAuth();
    } catch (e) {
      setAuthErr(e instanceof Error ? e.message : "Sign in failed.");
    }
    setAuthBusy(false);
  };

  const doRegister = async () => {
    setAuthBusy(true); setAuthErr(""); setAuthMsg("");
    try {
      const r = (await authService.register({
        email: reg.email.trim(), password: reg.password,
        first_name: reg.first_name.trim(), last_name: reg.last_name.trim(), phone: reg.phone.trim(),
      })) as unknown as { email?: string };
      if (r?.email) await refreshAuth();
      else setAuthMsg("If that address can be registered, you'll receive an email.");
    } catch (e) {
      setAuthErr(e instanceof Error ? e.message : "Registration failed.");
    }
    setAuthBusy(false);
  };

  const next = async () => {
    if (!user && (!name.trim() || !email.includes("@"))) {
      setError("Please enter your name and a valid email.");
      return;
    }
    if (phone.replace(/\D/g, "").length < 7) {
      setError("Please enter a valid contact phone number.");
      return;
    }
    if (forElse && !paxName.trim()) {
      setError("Please enter the passenger's name.");
      return;
    }
    // For signed-in bookers the booking takes its contact phone from the account,
    // so persist it when it's new or changed (best-effort — still proceed on error).
    if (user && phone.trim() !== (user.phone ?? "")) {
      try {
        await authService.updateProfile({ phone: phone.trim() });
        await refreshAuth();
      } catch { /* non-fatal: also carried in contact below */ }
    }
    setContact({
      name: (name || (user ? `${user.first_name} ${user.last_name}`.trim() : "")).trim(),
      email: (email || user?.email || "").trim(),
      phone: phone.trim(),
    });
    setTrip({
      forSomeoneElse: forElse,
      passengerName: forElse ? paxName.trim() : "",
      passengerPhone: forElse ? paxPhone.trim() : "",
    });
    router.push("/booking/payment");
  };

  const toggle = (p: Exclude<Panel, null>) => { setPanel(panel === p ? null : p); setAuthErr(""); setAuthMsg(""); };

  return (
    <section className="section">
      <div className="container-sub">
        <div className="box-row-tab mt-50">
          <div className="box-tab-left">
            <div className="box-content-detail">
              <h3 className="heading-24-medium color-text mb-20">Your details</h3>

              {!isLoading && !user && (
                <div className="mm-auth-gate mb-25">
                  {/* Sign in */}
                  <div className="mm-auth-row" onClick={() => toggle("signin")}>
                    <div>
                      <div className="mm-auth-t">Returning customer?</div>
                      <div className="mm-auth-s">Sign in to use your saved details.</div>
                    </div>
                    <button type="button" className="btn btn-default hover-up"
                      onClick={(e) => { e.stopPropagation(); toggle("signin"); }}>
                      {panel === "signin" ? "Close" : "Sign in"}
                    </button>
                  </div>
                  {panel === "signin" && (
                    <div className="mm-auth-form mm-signin-form">
                      <div className="row">
                        <div className="col-12 mb-15">
                          <label htmlFor="booking-signin-email" className="text-14">Email</label>
                          <input id="booking-signin-email" autoComplete="email" placeholder="you@example.com" type="email" className="form-control" value={li.email} onChange={(e) => setLi({ ...li, email: e.target.value })} />
                        </div>
                        <div className="col-12 mb-15">
                          <label htmlFor="booking-signin-password" className="text-14">Password</label>
                          <input id="booking-signin-password" autoComplete="current-password" placeholder="Your password" type="password" className="form-control" value={li.password} onChange={(e) => setLi({ ...li, password: e.target.value })} />
                        </div>
                      </div>
                      <p className="mb-15"><a className="mm-password-reset" href={`${API_BASE_URL.replace(/\/api\/?$/, "")}/accounts/password-reset/`}>Forgot password?</a></p>
                      {authErr && <p className="text-14" style={{ color: "#c0392b" }}>{authErr}</p>}
                      <button className="btn btn-primary hover-up" onClick={doLogin} disabled={authBusy}>
                        {authBusy ? "Signing in…" : "Sign in"}
                      </button>
                    </div>
                  )}

                  {/* Register */}
                  <div className="mm-auth-row" onClick={() => toggle("register")}>
                    <div>
                      <div className="mm-auth-t">New here?</div>
                      <div className="mm-auth-s">Create an account to track your rides.</div>
                    </div>
                    <button type="button" className="btn btn-default hover-up"
                      onClick={(e) => { e.stopPropagation(); toggle("register"); }}>
                      {panel === "register" ? "Close" : "Register"}
                    </button>
                  </div>
                  {panel === "register" && (
                    <div className="mm-auth-form">
                      <div className="row">
                        <div className="col-6 mb-15"><label className="text-14 color-grey">First name</label><input className="form-control" value={reg.first_name} onChange={(e) => setReg({ ...reg, first_name: e.target.value })} /></div>
                        <div className="col-6 mb-15"><label className="text-14 color-grey">Last name</label><input className="form-control" value={reg.last_name} onChange={(e) => setReg({ ...reg, last_name: e.target.value })} /></div>
                        <div className="col-12 mb-15"><label className="text-14 color-grey">Email</label><input type="email" className="form-control" value={reg.email} onChange={(e) => setReg({ ...reg, email: e.target.value })} /></div>
                        <div className="col-6 mb-15"><label className="text-14 color-grey">Password</label><input type="password" className="form-control" value={reg.password} onChange={(e) => setReg({ ...reg, password: e.target.value })} /></div>
                        <div className="col-6 mb-15"><label className="text-14 color-grey">Phone (optional)</label><input type="tel" className="form-control" value={reg.phone} onChange={(e) => setReg({ ...reg, phone: e.target.value })} /></div>
                      </div>
                      {authErr && <p className="text-14" style={{ color: "#c0392b" }}>{authErr}</p>}
                      {authMsg && <p className="text-14" style={{ color: "#1e7e34" }}>{authMsg}</p>}
                      <button className="btn btn-primary hover-up" onClick={doRegister} disabled={authBusy}>
                        {authBusy ? "Creating…" : "Create account"}
                      </button>
                    </div>
                  )}

                  <div className="mm-auth-guest">Or just continue as a guest — fill your details below.</div>
                </div>
              )}
              {user && (
                <div className="mm-auth-signedin mb-25">
                  Signed in as <b>{user.email}</b> — this booking will be saved to your account.
                </div>
              )}

              {!user && (
                <div className="row">
                  <div className="col-12 mb-20">
                    <label className="text-14 color-grey">Your full name</label>
                    <input type="text" className="form-control" value={name} onChange={(e) => setName(e.target.value)} />
                  </div>
                  <div className="col-12 mb-20">
                    <label className="text-14 color-grey">Your email <span className="color-grey">(receipt goes here)</span></label>
                    <input type="email" className="form-control" value={email} onChange={(e) => setEmail(e.target.value)} />
                  </div>
                  <div className="col-12 mb-20">
                    <label className="text-14 color-grey">Your phone number <span style={{ color: "#c0392b" }}>*</span> <span className="color-grey">(so the driver can reach you)</span></label>
                    <input type="tel" className="form-control" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="e.g. (512) 555-0142" required />
                  </div>
                </div>
              )}

              {user && (
                <div className="row">
                  <div className="col-12 mb-20">
                    <label className="text-14 color-grey">Your phone number <span style={{ color: "#c0392b" }}>*</span> <span className="color-grey">(so the driver can reach you)</span></label>
                    <input type="tel" className="form-control" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="e.g. (512) 555-0142" required />
                  </div>
                </div>
              )}

              <div className="mb-25">
                <label className="mm-check">
                  <input type="checkbox" checked={forElse} onChange={(e) => setForElse(e.target.checked)} />
                  <span className="mm-check-box" />
                  <span className="mm-check-label">I&rsquo;m booking for someone else</span>
                </label>
              </div>

              {forElse && (
                <div className="mm-pax-panel">
                  <p className="text-14 color-grey" style={{ margin: "0 0 12px" }}>Who is travelling?</p>
                  <div className="row">
                    <div className="col-6 mb-20">
                      <label className="text-14 color-grey">Passenger full name</label>
                      <input type="text" className="form-control" value={paxName} onChange={(e) => setPaxName(e.target.value)} placeholder="Name for the driver&rsquo;s sign" />
                    </div>
                    <div className="col-6 mb-20">
                      <label className="text-14 color-grey">Passenger phone (optional)</label>
                      <input type="tel" className="form-control" value={paxPhone} onChange={(e) => setPaxPhone(e.target.value)} placeholder="So the driver can reach them" />
                    </div>
                  </div>
                </div>
              )}

              {error && <p className="text-14" style={{ color: "#c0392b" }}>{error}</p>}
              <button className="btn btn-primary hover-up mt-10" onClick={next}>Continue to payment</button>
            </div>
          </div>
          <OrderSummary />
        </div>
      </div>
    </section>
  );
}
