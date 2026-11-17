export function notify(message: string) {
  window.dispatchEvent(new CustomEvent("client-feedback", { detail: message }));
}
export function clientDestination(value: string | null) {
  if (!value) return "/account";
  let destination: URL;
  try { destination = new URL(value, "https://storefront.invalid"); } catch { return "/account"; }
  const allowed = ["/account", "/booking/vehicle", "/booking/extra", "/booking/passenger", "/booking/payment", "/booking/confirmation"];
  if (destination.origin !== "https://storefront.invalid" || !allowed.includes(destination.pathname)) return "/account";
  return destination.pathname + destination.search + destination.hash;
}
