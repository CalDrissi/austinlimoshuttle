"use client";

import { useEffect, useMemo, useState } from "react";
import { loadStripe, type Stripe } from "@stripe/stripe-js";
import { Elements, CardElement, useStripe, useElements } from "@stripe/react-stripe-js";
import { paymentService } from "@/lib/api/payment.service";
import { cardsService } from "@/lib/api/cards.service";
import { ApiRequestError } from "@/lib/api/client";
import type { PaymentConfig } from "@/types/api";

// Stripe.js is loaded once per publishable key and reused — loadStripe injects a
// script tag, so calling it repeatedly is wasteful. Mirrors the booking payment step.
let stripeCache: { key: string; promise: Promise<Stripe | null> } | null = null;
function getStripe(pk: string) {
  if (!stripeCache || stripeCache.key !== pk) stripeCache = { key: pk, promise: loadStripe(pk) };
  return stripeCache.promise;
}

/** Add a new card on file via a Stripe SetupIntent. Calls `onAdded` once saved. */
export default function AddCard({ onAdded }: { onAdded: () => void }) {
  const [config, setConfig] = useState<PaymentConfig | null>(null);

  useEffect(() => {
    paymentService
      .config()
      .then(setConfig)
      .catch(() => setConfig({ enabled: false, publishable_key: "", mode: null }));
  }, []);

  const stripePromise = useMemo(
    () => (config?.enabled && config.publishable_key ? getStripe(config.publishable_key) : null),
    [config?.enabled, config?.publishable_key],
  );

  if (config && !config.enabled) {
    return <p className="text-14 color-grey">Adding a card is unavailable right now. Please contact us.</p>;
  }

  return (
    <Elements stripe={stripePromise}>
      <AddCardForm cardReady={!!config?.enabled} onAdded={onAdded} />
    </Elements>
  );
}

function AddCardForm({ cardReady, onAdded }: { cardReady: boolean; onAdded: () => void }) {
  const stripe = useStripe();
  const elements = useElements();

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const submit = async () => {
    if (saving) return;
    setError("");
    setSuccess("");
    if (!stripe || !elements) {
      setError("Card entry isn’t ready yet — give it a second and try again.");
      return;
    }
    const card = elements.getElement(CardElement);
    if (!card) {
      setError("Please enter your card details.");
      return;
    }
    setSaving(true);
    try {
      // Server creates/reuses the Stripe customer and returns a SetupIntent
      // secret. Card data goes straight to Stripe; it never touches our server.
      const intent = await cardsService.setupIntent();
      const result = await stripe.confirmCardSetup(intent.client_secret, {
        payment_method: { card },
      });
      if (result.error) {
        throw new Error(
          result.error.type === "card_error"
            ? result.error.message || "Card declined — try another card."
            : result.error.message || "The card could not be saved.",
        );
      }
      const pm = result.setupIntent?.payment_method;
      const pmId = typeof pm === "string" ? pm : pm?.id;
      if (!pmId) throw new Error("The card could not be saved.");
      // Persist it on file (the SetupIntent already attached it to the customer).
      await cardsService.save(pmId);
      card.clear();
      setComplete(false);
      setOpen(false);
      setSuccess("Card added.");
      onAdded();
    } catch (e) {
      if (e instanceof ApiRequestError && e.status === 503) {
        setError("Card payments are unavailable right now. Please contact us.");
      } else {
        setError(e instanceof Error ? e.message : "The card could not be saved.");
      }
    }
    setSaving(false);
  };

  if (!open) {
    return (
      <div style={{ marginTop: 10 }}>
        {success && <p className="text-14" style={{ color: "#1e7e34" }}>{success}</p>}
        <button className="btn btn-primary btn-sm hover-up" disabled={!cardReady} onClick={() => { setSuccess(""); setOpen(true); }}>
          Add card
        </button>
      </div>
    );
  }

  return (
    <div className="mm-ride" style={{ marginTop: 14 }}>
      <h6 className="text-16-medium mb-10">Add a card</h6>
      <div style={{ border: "1px solid #e5e5e5", borderRadius: 10, padding: "14px 16px", marginBottom: 12 }}>
        <CardElement
          options={{
            hidePostalCode: true,
            style: { base: { fontSize: "16px", color: "#0E0E0E", "::placeholder": { color: "#9a9a9a" } } },
          }}
          onChange={(e) => setComplete(e.complete)}
        />
      </div>
      {error && <p role="alert" className="text-14" style={{ color: "#c0392b" }}>{error}</p>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn-primary btn-sm hover-up" onClick={submit} disabled={saving || !stripe || !complete}>
          {saving ? "Saving…" : "Save card"}
        </button>
        <button className="btn btn-border btn-sm hover-up" disabled={saving} onClick={() => { setOpen(false); setError(""); }}>
          Cancel
        </button>
      </div>
    </div>
  );
}
