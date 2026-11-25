"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL } from "@/lib/api/config";
import { bookingService } from "@/lib/api/booking.service";
import type { BookingAmendRequest } from "@/lib/api/booking.service";
import { notify } from "@/lib/feedback";
import { authService } from "@/lib/api/auth.service";
import { useAuth, useRefreshAuth } from "@/hooks/useAuth";
import type { Booking } from "@/types/api";

type Tab = "overview" | "bookings" | "profile";

function money(a: string, c: string) {
  return `${c === "USD" ? "$" : c + " "}${Number(a).toFixed(2)}`;
}
function when(iso: string) {
  // Pickup times are Austin wall-clock; render them in the business timezone so
  // the card matches the edit form regardless of the viewer's browser timezone.
  return new Date(iso).toLocaleString("en-US", {
    weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    timeZone: "America/Chicago",
  });
}
function isUpcoming(b: Booking) {
  return b.status !== "cancelled" && b.status !== "completed" && new Date(b.pickup_at) > new Date();
}

// A stored pickup time (ISO, UTC) as an Austin wall-clock value for a
// <input type="datetime-local">. We show and send Austin local time; the server
// interprets a naive value in the business timezone (America/Chicago), matching
// how the original quote was taken.
function toAustinLocalInput(iso: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Chicago", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).formatToParts(new Date(iso));
  const g = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  return `${g("year")}-${g("month")}-${g("day")}T${g("hour")}:${g("minute")}`;
}

function RideCard({ b, onCancel, onAmend, userPhone }: {
  b: Booking;
  onCancel: (ref: string) => Promise<void>;
  onAmend: (ref: string, changes: BookingAmendRequest) => Promise<void>;
  userPhone: string;
}) {
  const [confirmCancellation, setConfirmCancellation] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState("");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [f, setF] = useState({
    passenger_count: b.passenger_count,
    luggage_count: b.luggage_count,
    flight_number: b.flight_number || "",
    pickup_sign: b.pickup_sign || "",
    notes: b.notes || "",
    phone: userPhone || "",
    pickup_at: toAustinLocalInput(b.pickup_at),
  });

  const cancellation = b.pending_cancellation ?? b.last_cancellation;
  const cancellationPending = cancellation?.status === "pending";

  const submitCancellation = async () => {
    if (cancelling || cancellationPending) return;
    setCancelling(true); setCancelError("");
    try {
      await onCancel(b.reference);
      setConfirmCancellation(false);
    } catch (e) {
      setCancelError(e instanceof Error ? e.message : "Could not submit your cancellation request.");
    } finally {
      setCancelling(false);
    }
  };

  const amendment = b.pending_amendment ?? b.last_amendment;
  const requestPending = amendment?.status === "pending";

  const save = async () => {
    if (saving || requestPending) return;
    setSaving(true); setErr("");
    try {
      await onAmend(b.reference, {
        passenger_count: f.passenger_count,
        luggage_count: f.luggage_count,
        flight_number: f.flight_number.trim(),
        pickup_sign: f.pickup_sign.trim(),
        notes: f.notes.trim(),
        phone: f.phone.trim(),
        pickup_at: f.pickup_at,  // Austin wall-clock; server reads it in business tz
      });
      setEditing(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not submit your change request.");
    }
    setSaving(false);
  };

  return (
    <div className="mm-ride">
      <div className="mm-ride-top">
        <div>
          <div className="route">{b.pickup_address} → {b.dropoff_address || "Hourly hire"}</div>
          <div className="meta">{when(b.pickup_at)} · {b.vehicle_name} · {money(b.total, b.currency)} · Ref {b.reference}</div>
          <div className="meta">Passengers {b.passenger_count} · Luggage {b.luggage_count}{b.flight_number ? ` · Flight ${b.flight_number}` : ""}</div>
        </div>
        <span className={`mm-badge ${b.status}`}>{b.status_display}</span>
      </div>

      {cancellation && (
        <div className="mm-feedback" role="status" style={{ marginTop: 14 }}>
          {cancellationPending ? "Cancellation requested — pending staff approval" : cancellation.status === "approved" ? "Cancellation request approved — booking cancelled" : "Cancellation request declined"}
          {cancellation.status === "declined" && cancellation.decline_reason && <p style={{ marginBottom: 0 }}>{cancellation.decline_reason}</p>}
        </div>
      )}

      {confirmCancellation && isUpcoming(b) && !cancellationPending && (
        <div className="mm-feedback" role="region" aria-label="Confirm cancellation request" style={{ marginTop: 14 }}>
          <p>Request cancellation? Staff will review it and issue any refund.</p>
          {cancelError && <p role="alert" style={{ color: "#c0392b" }}>{cancelError}</p>}
          <button className="btn btn-primary btn-sm hover-up" disabled={cancelling} onClick={submitCancellation}>{cancelling ? "Submitting…" : "Submit cancellation request"}</button>{" "}
          <button className="btn btn-border btn-sm hover-up" disabled={cancelling} onClick={() => setConfirmCancellation(false)}>Keep booking</button>
        </div>
      )}

      {amendment && (
        <div className="mm-feedback" role="status" style={{ marginTop: 14 }}>
          {requestPending ? "Change requested — pending staff approval" : amendment.status === "approved" ? "Change request approved" : "Change request declined"}
          {amendment.status === "declined" && amendment.decline_reason && <p style={{ marginBottom: 0 }}>{amendment.decline_reason}</p>}
        </div>
      )}

      {editing && !requestPending && (
        <div className="row" style={{ marginTop: 14 }}>
          <div className="col-12 mb-15"><p>Submit your proposed changes for staff approval. Your booking stays unchanged until approved.</p></div>
          <div className="col-12 mb-15"><label className="text-14 color-grey">Pickup date &amp; time</label><input type="datetime-local" className="form-control" value={f.pickup_at} onChange={(e) => setF({ ...f, pickup_at: e.target.value })} /><span className="text-13 color-grey">Changing the time may change the fare (night/event rates).</span></div>
          <div className="col-6 mb-15"><label className="text-14 color-grey">Passengers</label><input type="number" min={1} className="form-control" value={f.passenger_count} onChange={(e) => setF({ ...f, passenger_count: Math.max(1, Number(e.target.value)) })} /></div>
          <div className="col-6 mb-15"><label className="text-14 color-grey">Luggage</label><input type="number" min={0} className="form-control" value={f.luggage_count} onChange={(e) => setF({ ...f, luggage_count: Math.max(0, Number(e.target.value)) })} /></div>
          <div className="col-6 mb-15"><label className="text-14 color-grey">Flight number</label><input className="form-control" value={f.flight_number} onChange={(e) => setF({ ...f, flight_number: e.target.value })} /></div>
          <div className="col-6 mb-15"><label className="text-14 color-grey">Contact phone</label><input type="tel" className="form-control" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></div>
          <div className="col-12 mb-15"><label className="text-14 color-grey">Name on pickup sign</label><input className="form-control" value={f.pickup_sign} onChange={(e) => setF({ ...f, pickup_sign: e.target.value })} /></div>
          <div className="col-12 mb-15"><label className="text-14 color-grey">Notes for the driver</label><textarea className="form-control" rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></div>
          {err && <div className="col-12"><p role="alert" className="text-14" style={{ color: "#c0392b" }}>{err}</p></div>}
          <div className="col-12" style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary btn-sm hover-up" onClick={save} disabled={saving}>{saving ? "Submitting…" : "Submit change request"}</button>
            <button className="btn btn-border btn-sm hover-up" disabled={saving} onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="mm-ride-actions">
        <a className="btn btn-primary btn-sm hover-up" href={`${API_BASE_URL}/bookings/${b.reference}/receipt/`} target="_blank" rel="noopener noreferrer">Receipt PDF</a>
        {b.is_amendable && !requestPending && !editing && (
          <button className="btn btn-border btn-sm hover-up" onClick={() => {
            setF({ passenger_count: b.passenger_count, luggage_count: b.luggage_count,
              flight_number: b.flight_number || "", pickup_sign: b.pickup_sign || "",
              notes: b.notes || "", phone: userPhone || "", pickup_at: toAustinLocalInput(b.pickup_at) });
            setErr(""); setEditing(true);
          }}>Request changes</button>
        )}
        {isUpcoming(b) && !cancellationPending && !confirmCancellation && (
          <button className="btn btn-border btn-sm hover-up" style={{ color: "#c0392b" }} onClick={() => { setCancelError(""); setConfirmCancellation(true); }}>Request cancellation</button>
        )}
      </div>
      {!b.is_amendable && isUpcoming(b) && (
        <div className="meta" style={{ marginTop: 6, color: "#9aa1ac" }}>Online changes are closed for this trip — please contact us to make changes.</div>
      )}
      {/* Past/cancelled rides have no actions — say why instead of showing nothing. */}
      {b.status === "cancelled" && (
        <div className="meta" style={{ marginTop: 6, color: "#9aa1ac" }}>This booking was cancelled.</div>
      )}
      {b.status !== "cancelled" && !isUpcoming(b) && (
        <div className="meta" style={{ marginTop: 6, color: "#9aa1ac" }}>This ride has taken place.</div>
      )}
    </div>
  );
}

function AccountDashboard() {
  const params = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const { user, isLoading } = useAuth();
  const refreshAuth = useRefreshAuth();
  const [tab, setTab] = useState<Tab>("overview");
  const [actionError, setActionError] = useState("");
  useEffect(() => {
    const selected = params.get("tab");
    setTab(selected === "bookings" || selected === "profile" ? selected : "overview");
  }, [params]);
  const [pf, setPf] = useState({ first_name: "", last_name: "", email: "", phone: "" });
  const [pfMsg, setPfMsg] = useState({ text: "", ok: false });
  const [pfSaving, setPfSaving] = useState(false);

  useEffect(() => {
    if (!isLoading && !user) router.replace("/login?next=/account");
  }, [isLoading, user, router]);

  useEffect(() => {
    if (user) setPf({ first_name: user.first_name || "", last_name: user.last_name || "", email: user.email || "", phone: user.phone || "" });
  }, [user]);

  const saveProfile = async () => {
    const email = pf.email.trim();
    if (!email) {
      setPfMsg({ text: "An email address is required.", ok: false });
      return;
    }
    setPfSaving(true);
    setPfMsg({ text: "", ok: false });
    try {
      await authService.updateAccountProfile({
        first_name: pf.first_name.trim(),
        last_name: pf.last_name.trim(),
        email,
        phone: pf.phone.trim(),
      });
      await refreshAuth();
      setPfMsg({ text: "Saved.", ok: true });
    } catch (e) {
      setPfMsg({ text: e instanceof Error ? e.message : "Could not save.", ok: false });
    }
    setPfSaving(false);
  };

  const { data: bookings = [], isLoading: loadingBookings, isError: bookingsFailed } = useQuery({
    queryKey: ["my-bookings"],
    enabled: !!user,
    queryFn: () => bookingService.mine(),
    refetchInterval: 30_000,
  });

  const cancel = async (ref: string) => {
    const request = await bookingService.cancelRequest(ref);
    qc.setQueryData<Booking[]>(["my-bookings"], (current) => current?.map((b) =>
      b.reference === ref ? { ...b, pending_cancellation: request } : b
    ));
    notify("Cancellation requested — pending staff approval");
    void qc.invalidateQueries({ queryKey: ["my-bookings"] });
  };

  const amend = async (ref: string, changes: BookingAmendRequest) => {
    const request = await bookingService.amendRequest(ref, changes);
    qc.setQueryData<Booking[]>(["my-bookings"], (current) => current?.map((b) =>
      b.reference === ref ? { ...b, pending_amendment: request } : b
    ));
    notify("Change requested — pending staff approval");
    void qc.invalidateQueries({ queryKey: ["my-bookings"] });
  };

  const logout = async () => {
    try {
      await authService.logout(); qc.setQueryData(["me"], null);
      qc.removeQueries({ queryKey: ["my-bookings"] });
      notify("You've been signed out"); router.push("/");
    } catch { setActionError("Could not sign out — please try again."); }
  };

  if (isLoading || !user) return null;

  const upcoming = bookings.filter(isUpcoming).sort((a, b) => +new Date(a.pickup_at) - +new Date(b.pickup_at));
  const past = bookings.filter((b) => !isUpcoming(b));
  const initials = (user.first_name?.[0] || user.email[0] || "?").toUpperCase();

  const navBtn = (id: Tab, label: string) => (
    <button className={tab === id ? "on" : ""} onClick={() => { setTab(id); window.history.replaceState(null, "", id === "overview" ? "/account" : `/account?tab=${id}`); }}>{label}</button>
  );

  return (
    <section className="section pt-60 pb-80">
      <div className="container">
        <h2 className="heading-36-medium mb-30">My account</h2>
        {bookingsFailed && <p role="alert">We couldn't load your bookings. Please refresh to try again.</p>}
        {actionError && <p role="alert">{actionError}</p>}
        <div className="mm-acct">
          <aside className="mm-acct-side">
            <div className="mm-acct-user">
              <div className="mm-acct-avatar">{initials}</div>
              <div>
                <div style={{ fontWeight: 700, fontSize: 14 }}>{`${user.first_name} ${user.last_name}`.trim() || "Customer"}</div>
                <div style={{ fontSize: 12, color: "#9aa1ac" }}>{user.email}</div>
              </div>
            </div>
            <div className="mm-acct-nav">
              {navBtn("overview", "Overview")}
              {navBtn("bookings", "My bookings")}
              {navBtn("profile", "Profile")}
              <button className="signout" onClick={logout}>Sign out</button>
            </div>
          </aside>

          <div>
            {tab === "overview" && (
              <>
                <Link href="/" className="btn btn-primary hover-up mb-20">New booking</Link>
                <div className="mm-acct-kpis">
                  <div className="mm-acct-kpi"><div className="v">{upcoming.length}</div><div className="l">Upcoming rides</div></div>
                  <div className="mm-acct-kpi"><div className="v">{bookings.length}</div><div className="l">Total bookings</div></div>
                  <div className="mm-acct-kpi"><div className="v">{past.length}</div><div className="l">Completed / past</div></div>
                </div>
                <h5 className="text-18-medium mb-15">Next ride</h5>
                {loadingBookings && <p className="color-grey">Loading…</p>}
                {!loadingBookings && !bookingsFailed && upcoming.length === 0 && (
                  <div><p className="text-16 color-grey">No upcoming rides.</p><Link href="/" className="btn btn-primary hover-up">New booking</Link></div>
                )}
                {upcoming.slice(0, 1).map((b) => <RideCard key={b.reference} b={b} onCancel={cancel} onAmend={amend} userPhone={user.phone || ""} />)}
              </>
            )}

            {tab === "bookings" && (
              <>
                <h5 className="text-18-medium mb-15">All bookings</h5>
                {loadingBookings && <p className="color-grey">Loading…</p>}
                {!loadingBookings && !bookingsFailed && bookings.length === 0 && (
                  <div><p className="text-16 color-grey">No bookings yet.</p><Link href="/" className="btn btn-primary hover-up">New booking</Link></div>
                )}
                {[...upcoming, ...past].map((b) => <RideCard key={b.reference} b={b} onCancel={cancel} onAmend={amend} userPhone={user.phone || ""} />)}
              </>
            )}

            {tab === "profile" && (
              <>
                <h5 className="text-18-medium mb-15">Profile</h5>
                <div className="mm-ride">
                  <div className="row">
                    <div className="col-6 mb-20">
                      <label className="text-14 color-grey">First name</label>
                      <input className="form-control" value={pf.first_name} onChange={(e) => setPf({ ...pf, first_name: e.target.value })} />
                    </div>
                    <div className="col-6 mb-20">
                      <label className="text-14 color-grey">Last name</label>
                      <input className="form-control" value={pf.last_name} onChange={(e) => setPf({ ...pf, last_name: e.target.value })} />
                    </div>
                    <div className="col-6 mb-20">
                      <label className="text-14 color-grey">Phone</label>
                      <input className="form-control" type="tel" value={pf.phone} onChange={(e) => setPf({ ...pf, phone: e.target.value })} />
                    </div>
                    <div className="col-6 mb-20">
                      <label className="text-14 color-grey">Email <span className="color-grey">(this is your sign-in)</span></label>
                      <input className="form-control" type="email" value={pf.email} onChange={(e) => setPf({ ...pf, email: e.target.value })} />
                    </div>
                  </div>
                  <div className="d-flex align-items-center" style={{ gap: 14 }}>
                    <button className="btn btn-primary hover-up" onClick={saveProfile} disabled={pfSaving}>
                      {pfSaving ? "Saving…" : "Save changes"}
                    </button>
                    {pfMsg.text && <span role={pfMsg.ok ? "status" : "alert"} className="text-14" style={{ color: pfMsg.ok ? "#1e7e34" : "#c0392b" }}>{pfMsg.text}</span>}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

export default function AccountPage() { return <Suspense fallback={<p role="status">Loading your account…</p>}><AccountDashboard /></Suspense>; }
