"use client";

import { useEffect, useMemo, useState, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { loadStripe, type Stripe } from "@stripe/stripe-js";
import { Elements, CardElement, useStripe, useElements } from "@stripe/react-stripe-js";
import { useBookingStore, useHydrated } from "@/lib/booking/store";
import { useAuth } from "@/hooks/useAuth";
import { bookingService } from "@/lib/api/booking.service";
import { quoteService, quoteRequest } from "@/lib/api/quote.service";
import { paymentService } from "@/lib/api/payment.service";
import { ApiRequestError } from "@/lib/api/client";
import { useCapacity } from "@/lib/booking/useCapacity";
import { saveConfirmationSnapshot } from "@/lib/booking/confirmation";
import { money } from "@/lib/format";
import AuthModal from "@/components/booking/AuthModal";
import FlowRail from "@/components/booking/FlowRail";
import OfferCode from "@/components/booking/OfferCode";
import type { PaymentConfig } from "@/types/api";

type Method = "cash" | "card";

// Stripe.js is loaded once per publishable key and reused across renders and
// navigation — loadStripe injects a script tag, so calling it repeatedly is wasteful.
let stripeCache: { key: string; promise: Promise<Stripe | null> } | null = null;
function getStripe(pk: string) {
  if (!stripeCache || stripeCache.key !== pk) stripeCache = { key: pk, promise: loadStripe(pk) };
  return stripeCache.promise;
}

export default function BookingPaymentPage() {
  const [config, setConfig] = useState<PaymentConfig | null>(null);

  useEffect(() => {
    paymentService
      .config()
      .then(setConfig)
      .catch(() => setConfig({ enabled: false, publishable_key: "", mode: null }));
  }, []);

  // stripe={null} is Stripe's documented "still loading" state, so it is safe to
  // render <Elements> before config arrives or when card payments are disabled.
  const stripePromise = useMemo(
    () => (config?.enabled && config.publishable_key ? getStripe(config.publishable_key) : null),
    [config?.enabled, config?.publishable_key],
  );

  return (
    <Elements stripe={stripePromise}>
      <PaymentForm cardEnabled={!!config?.enabled} />
    </Elements>
  );
}

function PaymentForm({ cardEnabled }: { cardEnabled: boolean }) {
  const router = useRouter();
  const qc = useQueryClient();
  const stripe = useStripe();
  const elements = useElements();
  const { user } = useAuth();

  const quote = useBookingStore((s) => s.quote);
  const search = useBookingStore((s) => s.search);
  const trip = useBookingStore((s) => s.trip);
  const contact = useBookingStore((s) => s.contact);
  const setReference = useBookingStore((s) => s.setReference);
  const [authModal, setAuthModal] = useState<"login" | "register" | null>(null);

  // Default to card once we know it's available (config loads async), unless the
  // customer has already picked a method themselves.
  const [method, setMethod] = useState<Method>("cash");
  const [methodTouched, setMethodTouched] = useState(false);
  useEffect(() => {
    if (!methodTouched && cardEnabled) setMethod("card");
  }, [methodTouched, cardEnabled]);

  const submissionLock = useRef(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  // Quote tokens are short-lived; when one dies at confirm the fix is a fresh
  // quote, not a trip back through the funnel — one click, same step.
  const [expired, setExpired] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [cardComplete, setCardComplete] = useState(false);
  // The booking is created on the first confirm and reused on retry, so a
  // declined card doesn't leave a trail of duplicate pending bookings.
  const [createdRef, setCreatedRef] = useState("");
  const setUnpaid = useBookingStore((s) => s.setUnpaid);
  const hydrated = useHydrated();
  const capacity = useCapacity();

  // The created-but-unpaid booking is only valid for the exact quote +
  // details it was created from. Same fingerprint -> adopt it (retry after a
  // declined card, or coming back to this step). Different -> the customer
  // changed their trip or identity, so VOID the stale pending on the server
  // instead of leaving it as phantom work for the office.
  const fingerprint = JSON.stringify({ t: quote?.quote_token, trip, contact });
  useEffect(() => {
    setExpired(false);
    const unpaid = useBookingStore.getState().unpaid;
    if (unpaid && unpaid.fingerprint === fingerprint) {
      setCreatedRef(unpaid.reference);
      return;
    }
    setCreatedRef("");
    if (unpaid) {
      setUnpaid(null);
      // Best-effort: a 409 means it got confirmed/paid after all — leave it.
      bookingService.voidPending(unpaid.reference).catch(() => {});
    }
  }, [fingerprint, setUnpaid]);

  useEffect(() => {
    if (hydrated && !quote) router.replace("/booking/vehicle");
  }, [hydrated, quote, router]);
  useEffect(() => {
    if (hydrated && capacity.over) router.replace("/booking/extra");
  }, [hydrated, capacity.over, router]);
  if (!hydrated || !quote) return null;

  const confirm = async () => {
    if (submissionLock.current) return;
    if (capacity.blocked) { setError("Check vehicle capacity before payment."); return; }
    submissionLock.current = true;
    setSubmitting(true);
    setError("");
    try {
      // Create the booking once (reuse the reference on retry).
      let reference = createdRef;
      if (!reference) {
        // Booking for someone else: the passenger's name goes on the driver's
        // pickup sign and their phone into the notes (the booker stays the contact).
        const pickupSign = trip.forSomeoneElse && trip.passengerName ? trip.passengerName : trip.pickupSign;
        const notes = [
          trip.notes,
          trip.forSomeoneElse && trip.passengerPhone ? `Passenger phone: ${trip.passengerPhone}` : "",
        ].filter(Boolean).join(" — ");

        const booking = await bookingService.create({
          quote_token: quote.quote_token,
          passenger_count: trip.passengerCount,
          luggage_count: trip.luggageCount,
          pickup_sign: pickupSign,
          notes,
          // Signed-in bookings take their identity from the account; sending
          // guest_* here would carry a previous guest's details into the booking.
          ...(user ? {} : {
            guest_email: contact.email,
            guest_name: contact.name,
            guest_phone: contact.phone,
          }),
        });
        reference = booking.reference;
        setCreatedRef(reference);
        setReference(reference);
        setUnpaid({ reference, fingerprint });
      }

      if (method === "cash") {
        // Confirmed immediately — the driver collects the fare.
        await paymentService.payCash(reference);
      } else {
        if (!stripe || !elements) {
          throw new Error("Card payments aren’t ready yet — give it a second and try again.");
        }
        const card = elements.getElement(CardElement);
        if (!card) throw new Error("Please enter your card details.");

        // Start the intent (server sets setup_future_usage for signed-in owners,
        // so a successful charge also saves the card), then confirm the card.
        // Card data goes straight to Stripe; it never touches our server.
        const intent = await paymentService.createIntent(reference);
        const result = await stripe.confirmCardPayment(intent.client_secret, {
          payment_method: {
            card,
            billing_details: {
              name: contact.name || undefined,
              email: contact.email || undefined,
            },
          },
        });
        if (result.error) {
          throw new Error(result.error.type === "card_error" ? "Card declined — try another card" : result.error.message || "The card could not be charged.");
        }
        // succeeded / processing — the webhook is what actually confirms the booking.
      }

      // Settled: the pending is no longer voidable work, and the confirmation
      // page must survive a refresh after the draft store is cleared.
      setUnpaid(null);
      saveConfirmationSnapshot(reference, {
        search: useBookingStore.getState().search,
        vehicleName: quote.vehicle_name, total: quote.total, currency: quote.currency,
        contact, trip, method,
      });
      void qc.invalidateQueries({ queryKey: ["my-bookings"] });
      router.push("/booking/confirmation");
    } catch (e) {
      if (e instanceof ApiRequestError && e.status === 409 && createdRef && /already paid/i.test(e.message)) {
        // Already settled (double submit, second tab, back-button replay):
        // the right destination is this booking's confirmation, not an error.
        setUnpaid(null);
        setReference(createdRef);
        saveConfirmationSnapshot(createdRef, {
          search: useBookingStore.getState().search,
          vehicleName: quote.vehicle_name, total: quote.total, currency: quote.currency,
          contact, trip, method,
        });
        void qc.invalidateQueries({ queryKey: ["my-bookings"] });
        router.push("/booking/confirmation");
        return;
      }
      if (e instanceof ApiRequestError && e.fieldError("quote_token")) {
        setExpired(true); // dedicated recovery UI below; no generic error
      } else if (e instanceof ApiRequestError && e.status === 503) {
        setError("Card payments are unavailable right now. Please choose cash, or contact us.");
      } else {
        setError(e instanceof Error ? e.message : "Something went wrong creating your booking.");
      }
      submissionLock.current = false;
      setSubmitting(false);
    }
  };

  // One click back to a bookable state: re-run the same search, adopt the fresh
  // prices/tokens (applyRequote re-points the chosen vehicle), stay right here.
  const refreshPrices = async () => {
    const { search, applyRequote } = useBookingStore.getState();
    if (!search || refreshing) return;
    setRefreshing(true);
    setError("");
    try {
      const response = await quoteService.create(quoteRequest(search));
      qc.setQueryData(["quotes", search], response);
      applyRequote(search, response);
      setExpired(false);
      if (!response.quotes.some((q) => q.vehicle_id === quote.vehicle_id)) {
        // Vehicle no longer offered for this trip — the cleared selection
        // sends the booker back to choose (guard effect above).
        return;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "We couldn't refresh your prices — please try again.");
    } finally {
      setRefreshing(false);
    }
  };

  const methodBox = (m: Method, title: string, sub: string, disabled = false) => (
    <label
      style={{
        display: "block", border: `1px solid ${method === m ? "#0E0E0E" : "#e5e5e5"}`,
        borderRadius: 10, padding: "12px 16px", marginBottom: 10,
        cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.55 : 1,
      }}
    >
      <input
        type="radio" name="method" style={{ marginRight: 8 }}
        checked={method === m} disabled={disabled || submitting}
        onChange={() => { setMethod(m); setMethodTouched(true); }}
      />
      <b>{title}</b>
      <div className="text-14 color-grey" style={{ marginLeft: 24 }}>{sub}</div>
    </label>
  );

  const cardDisabledSubmit = method === "card" && (!stripe || !cardComplete);

  return (
    <section className="blv">
      <div className="blv-page">
        <div className="blv-layout">
          <div className="blv-main">
            <h1 className="blv-title">Review &amp; confirm</h1>
            <div className="flow-card">

        <div style={{ border: "1px solid #eee", borderRadius: 12, padding: 20, marginBottom: 24 }}>
          <div className="d-flex justify-content-between mb-10">
            <span className="text-16-medium">{quote.vehicle_name}</span>
          </div>
          <div className="d-flex justify-content-between heading-20-medium">
            <span>Total</span><span>{money(quote.total, quote.currency)}</span>
          </div>
          {search?.tripType === "hourly" && !!search.hours && (
            <p className="text-14 color-grey" style={{ margin: "4px 0 0", textAlign: "right" }}>
              for {search.hours} hour{search.hours === 1 ? "" : "s"} at your disposal
            </p>
          )}
          <p className="text-13 color-grey" style={{ margin: "8px 0 0" }}>
            Quoted prices are held for a short time — if yours expires we&rsquo;ll refresh it right here.
          </p>
        </div>

        <OfferCode />

        <h5 className="text-16-medium mb-10">How would you like to pay?</h5>
        {methodBox(
          "card", "Pay by card",
          cardEnabled ? "Pay securely now by credit or debit card." : "Card payment is unavailable right now.",
          !cardEnabled,
        )}
        {methodBox("cash", "Cash — pay the driver", "Confirm now, pay in the vehicle. No card needed.")}

        {method === "card" && cardEnabled && (
          <div style={{ marginBottom: 14 }}>
            <div style={{ border: "1px solid #e5e5e5", borderRadius: 10, padding: "14px 16px" }}>
              <CardElement
                options={{
                  hidePostalCode: true,
                  style: { base: { fontSize: "16px", color: "#0E0E0E", "::placeholder": { color: "#9a9a9a" } } },
                }}
                onChange={(e) => setCardComplete(e.complete)}
              />
            </div>
            {user ? (
              <p className="text-14 color-grey mt-10" style={{ marginBottom: 0 }}>
                <i className="bi bi-shield-check" style={{ marginRight: 6 }} />
                Your card is saved securely for faster checkout next time. You can remove it anytime in your account.
              </p>
            ) : (
              <p className="text-14 color-grey mt-10" style={{ marginBottom: 0 }}>
                Want one-tap booking next time?{" "}
                <button type="button" className="mm-quiet-link" onClick={() => setAuthModal("login")}>Sign in</button>
                {" "}to keep your card on file.
              </p>
            )}
          </div>
        )}

              {expired && (
                <div className="mm-quote-expired" role="alert">
                  <p style={{ margin: 0 }}>
                    <b>Your quote expired.</b> Prices are held for a limited time — refresh to get
                    today&rsquo;s price for the same trip. All your details are kept.
                  </p>
                  <button type="button" className="btn btn-primary hover-up" onClick={refreshPrices} disabled={refreshing}>
                    {refreshing ? "Getting fresh prices…" : "Get fresh prices"}
                  </button>
                </div>
              )}
              {error && <p role="alert" className="text-14" style={{ color: "#c0392b" }}>{error}</p>}
              {submitting && (
                <p role="status" className="text-14 color-grey mt-10" style={{ marginBottom: 0 }}>
                  Confirming your booking — this usually takes a moment. Please don&rsquo;t close this page.
                </p>
              )}
            </div>
          </div>
          <FlowRail
            step="payment"
            cta={{
              label: submitting ? "Processing payment…" : method === "cash" ? "Confirm booking" : `Pay ${money(quote.total, quote.currency)}`,
              onClick: () => void confirm(),
              disabled: cardDisabledSubmit || capacity.blocked || expired || refreshing,
              busy: submitting,
            }}
          />
        </div>
      </div>

      <AuthModal open={authModal !== null} initialTab={authModal ?? "login"} onClose={() => setAuthModal(null)} />
    </section>
  );
}
