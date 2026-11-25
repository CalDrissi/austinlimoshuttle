/**
 * One place for customer-facing money and date/time formatting.
 *
 * Every page renders the same shapes: "$1,234.56", "Fri, Nov 28, 2026",
 * "2:05 PM" (US, 12-hour, Austin business timezone for timestamps). The
 * booking flow stores dates as "YYYY-MM-DD" and times as either "h:mm AM/PM"
 * (TimePicker) or "HH:mm" (a native <input type="time"> after an in-flow
 * edit) — the formatters below accept both so no page ever leaks an ISO date
 * or a 24-hour clock to the customer.
 */

const moneyFormats = new Map<string, Intl.NumberFormat>();

/** "1234.5" -> "$1,234.50". Currency-aware; amounts arrive as API strings. */
export function money(amount: string | number, currency = "USD"): string {
  let format = moneyFormats.get(currency);
  if (!format) {
    format = new Intl.NumberFormat("en-US", { style: "currency", currency });
    moneyFormats.set(currency, format);
  }
  return format.format(Number(amount));
}

/**
 * Blacklane prints "US$ 167.94" on the vehicle cards; keep that anatomy (the
 * vehicle step is A/B'd against live Blacklane) but with grouped thousands.
 */
export function moneyBlacklane(amount: string | number, currency = "USD"): string {
  if (currency !== "USD") return money(amount, currency);
  const grouped = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(Number(amount));
  return `US$ ${grouped}`;
}

/** "2026-11-28" -> "Fri, Nov 28, 2026" without the UTC shift of new Date(string). */
export function formatDate(ymd: string): string {
  const m = ymd.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return ymd;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).toLocaleDateString(
    "en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" },
  );
}

/** "14:05" or "2:05 pm" -> "2:05 PM". Anything unrecognised passes through. */
export function formatTime(time: string): string {
  const ampm = time.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  if (ampm) return `${Number(ampm[1])}:${ampm[2]} ${ampm[3].toUpperCase()}`;
  const h24 = time.match(/^(\d{1,2}):(\d{2})$/);
  if (!h24) return time;
  const hour = Number(h24[1]);
  return `${hour % 12 || 12}:${h24[2]} ${hour < 12 ? "AM" : "PM"}`;
}

/** ISO timestamp -> "Fri, Nov 28, 2:05 PM" in the business timezone. */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    weekday: "short", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", timeZone: "America/Chicago",
  });
}
