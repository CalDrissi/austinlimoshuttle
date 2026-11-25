"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useBookingStore, useHydrated } from "@/lib/booking/store";
import { useAuth, useRefreshAuth } from "@/hooks/useAuth";
import { authService } from "@/lib/api/auth.service";
import { useCapacity } from "@/lib/booking/useCapacity";
import AuthModal from "@/components/booking/AuthModal";
import FlowRail from "@/components/booking/FlowRail";

/**
 * Step 3 only REFLECTS the identity decided on step 1 (owner blueprint):
 * guests fill Name/Email/Phone with one quiet "Have an account? Sign in" line
 * opening the same AuthModal the rail uses; signed-in bookers see their
 * prefilled details plus the "booking for someone else" toggle. The old
 * triple-ask (segmented control + Returning-customer + New-here rows with
 * their own inline auth forms) is gone.
 */
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
  const capacity = useCapacity();

  const [name, setName] = useState(contact.name ?? "");
  const [email, setEmail] = useState(contact.email ?? "");
  const [phone, setPhone] = useState(contact.phone ?? "");
  const [forElse, setForElse] = useState(!!trip.forSomeoneElse);
  const [paxName, setPaxName] = useState(trip.passengerName ?? "");
  const [paxPhone, setPaxPhone] = useState(trip.passengerPhone ?? "");
  const [error, setError] = useState("");
  const [authModal, setAuthModal] = useState<"login" | "register" | null>(null);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const touch = (key: string) => setTouched((old) => ({ ...old, [key]: true }));
  const invalid = (key: string, value: string) => touched[key] && (key === "email" ? !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim()) : key === "phone" ? value.replace(/\D/g, "").length < 7 : key === "paxPhone" ? !!value.trim() && value.replace(/\D/g, "").length < 7 : !value.trim());
  const [detailsReady, setDetailsReady] = useState(false);
  useEffect(() => {
    if (!hydrated) return;
    const saved = useBookingStore.getState();
    setName(saved.contact.name ?? ""); setEmail(saved.contact.email ?? ""); setPhone(saved.contact.phone ?? "");
    setForElse(!!saved.trip.forSomeoneElse); setPaxName(saved.trip.passengerName ?? ""); setPaxPhone(saved.trip.passengerPhone ?? "");
    setDetailsReady(true);
  }, [hydrated]);

  useEffect(() => {
    if (hydrated && !quote) router.replace("/booking/vehicle");
  }, [hydrated, quote, router]);

  // A signed-in booker's identity IS the account: replace (don't just backfill)
  // whatever guest details were typed before sign-in, once per account, so the
  // step shows — and the booking carries — the account's name and email.
  const appliedAccount = useRef<string | null>(null);
  useEffect(() => {
    if (!user) { appliedAccount.current = null; return; }
    if (!detailsReady || appliedAccount.current === user.email) return;
    appliedAccount.current = user.email;
    setName(`${user.first_name} ${user.last_name}`.trim());
    setEmail(user.email);
    // Keep a phone the booker already typed when the account has none on file.
    setPhone((p) => user.phone || p);
  }, [user, detailsReady]);

  // Persist as the passenger types so the summary and back navigation stay live.
  useEffect(() => {
    if (!detailsReady) return;
    setContact({ name, email, phone });
    setTrip({ forSomeoneElse: forElse, passengerName: paxName, passengerPhone: paxPhone });
  }, [detailsReady, name, email, phone, forElse, paxName, paxPhone, setContact, setTrip]);

  useEffect(() => {
    if (hydrated && capacity.over) router.replace("/booking/extra");
  }, [hydrated, capacity.over, router]);
  if (!hydrated || !quote) return null;

  const next = async () => {
    if (capacity.blocked) { setError("Check passengers and luggage against your vehicle capacity before payment."); return; }
    if (!user && (!name.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()))) {
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
    if (forElse && paxPhone.trim() && paxPhone.replace(/\D/g, "").length < 7) { setError("Please enter a valid passenger phone number."); return; }
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

  return (
    <section className="blv">
      <div className="blv-page">
        <div className="blv-layout">
          <div className="blv-main">
            <h1 className="blv-title">Your details</h1>
            <div className="flow-card">
              {user && (
                <div className="mm-auth-signedin mb-25">
                  Welcome back, {user.first_name || "traveler"}. Signed in as <b>{user.email}</b> — this booking will be saved to your account.
                </div>
              )}

              {!user && (
                <div className="row">
                  <div className="col-12 mb-20">
                    <label htmlFor="guest-name" className="text-14 color-grey">Your full name</label>
                    <input id="guest-name" type="text" className="form-control" value={name} onBlur={() => touch("name")} aria-invalid={!!invalid("name", name)} onChange={(e) => setName(e.target.value)} />
                    {invalid("name", name) && <p role="alert" className="mm-field-error">Enter your full name.</p>}
                  </div>
                  <div className="col-12 mb-20">
                    <label htmlFor="guest-email" className="text-14 color-grey">Your email <span className="color-grey">(receipt goes here)</span></label>
                    <input id="guest-email" type="email" className="form-control" value={email} onBlur={() => touch("email")} aria-invalid={!!invalid("email", email)} onChange={(e) => setEmail(e.target.value)} />
                    {invalid("email", email) && <p role="alert" className="mm-field-error">Enter a valid email address.</p>}
                  </div>
                  <div className="col-12 mb-20">
                    <label htmlFor="guest-phone" className="text-14 color-grey">Your phone number <span style={{ color: "#c0392b" }}>*</span> <span className="color-grey">(so the driver can reach you)</span></label>
                    <input id="guest-phone" type="tel" className="form-control" value={phone} onBlur={() => touch("phone")} aria-invalid={!!invalid("phone", phone)} onChange={(e) => setPhone(e.target.value)} placeholder="e.g. (512) 555-0142" required />
                    {invalid("phone", phone) && <p role="alert" className="mm-field-error">Enter a valid phone number.</p>}
                  </div>
                </div>
              )}

              {!isLoading && !user && (
                <p className="text-14 color-grey mb-25">
                  Have an account?{" "}
                  <button type="button" className="mm-quiet-link" onClick={() => setAuthModal("login")}>Sign in</button>
                  {" "}to use your saved details.
                </p>
              )}

              {user && (
                <div className="row">
                  <div className="col-12 mb-20">
                    <label htmlFor="account-phone" className="text-14 color-grey">Your phone number <span style={{ color: "#c0392b" }}>*</span> <span className="color-grey">(so the driver can reach you)</span></label>
                    <input id="account-phone" type="tel" className="form-control" value={phone} onBlur={() => touch("phone")} aria-invalid={!!invalid("phone", phone)} onChange={(e) => setPhone(e.target.value)} placeholder="e.g. (512) 555-0142" required />
                    {invalid("phone", phone) && <p role="alert" className="mm-field-error">Enter a valid phone number.</p>}
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
                      <label htmlFor="pax-name" className="text-14 color-grey">Passenger full name</label>
                      <input id="pax-name" type="text" className="form-control" value={paxName} onBlur={() => touch("paxName")} aria-invalid={!!invalid("paxName", paxName)} onChange={(e) => setPaxName(e.target.value)} placeholder="Name for the driver&rsquo;s sign" />
                    {invalid("paxName", paxName) && <p role="alert" className="mm-field-error">Enter the passenger’s name.</p>}
                    </div>
                    <div className="col-6 mb-20">
                      <label htmlFor="pax-phone" className="text-14 color-grey">Passenger phone (optional)</label>
                      <input id="pax-phone" type="tel" className="form-control" value={paxPhone} onBlur={() => touch("paxPhone")} aria-invalid={!!invalid("paxPhone", paxPhone)} onChange={(e) => setPaxPhone(e.target.value)} placeholder="So the driver can reach them" />
                    {invalid("paxPhone", paxPhone) && <p role="alert" className="mm-field-error">Enter a valid phone number or leave it blank.</p>}
                    </div>
                  </div>
                </div>
              )}

              {error && <p role="alert" className="text-14" style={{ color: "#c0392b" }}>{error}</p>}
            </div>
          </div>
          <FlowRail step="passenger" cta={{ label: "Continue to payment", onClick: () => void next(), disabled: capacity.blocked }} />
        </div>
      </div>

      <AuthModal open={authModal !== null} initialTab={authModal ?? "login"} onClose={() => setAuthModal(null)} />
    </section>
  );
}
