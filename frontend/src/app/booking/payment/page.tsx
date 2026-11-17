"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { loadStripe, type Stripe } from "@stripe/stripe-js";
import { Elements, CardElement, useStripe, useElements } from "@stripe/react-stripe-js";
import { useBookingStore, useHydrated } from "@/lib/booking/store";
import { useAuth } from "@/hooks/useAuth";
import { bookingService } from "@/lib/api/booking.service";
import { paymentService } from "@/lib/api/payment.service";
import { ApiRequestError } from "@/lib/api/client";
import { useCapacity } from "@/lib/booking/useCapacity";
import OrderSummary from "@/components/booking/OrderSummary";
import type { PaymentConfig } from "@/types/api";

type Method = "cash" | "card";

function money(amount: string, currency: string) {
  const symbol = currency === "USD" ? "$" : `${currency} `;
  return `${symbol}${Number(amount).toFixed(2)}`;
}

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
  const stripe = useStripe();
  const elements = useElements();
  const { user } = useAuth();

  const quote = useBookingStore((s) => s.quote);
  const trip = useBookingStore((s) => s.trip);
  const contact = useBookingStore((s) => s.contact);
  const setReference = useBookingStore((s) => s.setReference);

  // Default to card once we know it's available (config loads async), unless the
  // customer has already picked a method themselves.
  const [method, setMethod] = useState<Method>("cash");
  const [methodTouched, setMethodTouched] = useState(false);
  useEffect(() => {
    if (!methodTouched && cardEnabled) setMethod("card");
  }, [methodTouched, cardEnabled]);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [cardComplete, setCardComplete] = useState(false);
  // The booking is created on the first confirm and reused on retry, so a
  // declined card doesn't leave a trail of duplicate pending bookings.
  const [createdRef, setCreatedRef] = useState("");
  useEffect(() => { setCreatedRef(""); }, [quote?.quote_token, trip, contact]);
  const hydrated = useHydrated();
  const capacity = useCapacity();

  useEffect(() => {
    if (hydrated && !quote) router.replace("/booking/vehicle");
  }, [hydrated, quote, router]);
  useEffect(() => {
    if (hydrated && capacity.over) router.replace("/booking/extra");
  }, [hydrated, capacity.over, router]);
  if (!hydrated || !quote) return null;

  const confirm = async () => {
    if (capacity.blocked) { setError("Check vehicle capacity before payment."); return; }
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
          flight_number: trip.flightNumber,
          pickup_sign: pickupSign,
          notes,
          guest_email: contact.email,
          guest_name: contact.name,
          guest_phone: contact.phone,
        });
        reference = booking.reference;
        setCreatedRef(reference);
        setReference(reference);
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
          throw new Error(result.error.message || "The card could not be charged.");
        }
        // succeeded / processing — the webhook is what actually confirms the booking.
      }

      router.push("/booking/confirmation");
    } catch (e) {
      if (e instanceof ApiRequestError && e.status === 503) {
        setError("Card payments are unavailable right now. Please choose cash, or contact us.");
      } else {
        setError(e instanceof Error ? e.message : "Something went wrong creating your booking.");
      }
      setSubmitting(false);
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
        checked={method === m} disabled={disabled}
        onChange={() => { setMethod(m); setMethodTouched(true); }}
      />
      <b>{title}</b>
      <div className="text-14 color-grey" style={{ marginLeft: 24 }}>{sub}</div>
    </label>
  );

  const cardDisabledSubmit = method === "card" && (!stripe || !cardComplete);

  return (
    <section className="section">
      <div className="container-sub">
        <div className="box-row-tab mt-50">
          <div className="box-tab-left">
            <div className="box-content-detail">
              <h3 className="heading-24-medium color-text mb-20">Review &amp; confirm</h3>

        <div style={{ border: "1px solid #eee", borderRadius: 12, padding: 20, marginBottom: 24 }}>
          <div className="d-flex justify-content-between mb-10">
            <span className="text-16-medium">{quote.vehicle_name}</span>
          </div>
          <div className="d-flex justify-content-between heading-20-medium">
            <span>Total</span><span>{money(quote.total, quote.currency)}</span>
          </div>
        </div>

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
                Want one-tap booking next time? <a href="/login">Sign in</a> to keep your card on file.
              </p>
            )}
          </div>
        )}

              {error && <p className="text-14" style={{ color: "#c0392b" }}>{error}</p>}
              <button
                className="btn btn-primary hover-up mt-10"
                onClick={confirm}
                disabled={submitting || cardDisabledSubmit || capacity.blocked}
              >
                {submitting
                  ? "Processing…"
                  : method === "cash"
                    ? "Confirm booking (cash)"
                    : `Pay ${money(quote.total, quote.currency)}`}
              </button>
            </div>
          </div>
          <OrderSummary />
        </div>
      </div>
    </section>
  );
}
