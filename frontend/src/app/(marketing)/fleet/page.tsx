import type { Metadata } from "next";
import FleetPageClient from "./FleetPageClient";

// A server wrapper exists purely for the metadata API: setting document.title
// from a client effect loses to the app router re-applying the layout default.
export const metadata: Metadata = { title: "Our Fleet" };

export default function FleetPage() {
  return <FleetPageClient />;
}
