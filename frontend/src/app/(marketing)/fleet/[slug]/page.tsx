import type { Metadata } from "next";
import { API_BASE_URL } from "@/lib/api/config";
import type { Vehicle } from "@/types/api";
import FleetDetailClient from "./FleetDetailClient";

// A server wrapper exists purely for the metadata API: setting document.title
// from a client effect loses to the app router re-applying the layout default.
// The layout template appends "| M&M Austin Limousine".
export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> },
): Promise<Metadata> {
  const { slug } = await params;
  try {
    const res = await fetch(`${API_BASE_URL}/vehicles/`, {
      next: { revalidate: 3600 },
    });
    if (res.ok) {
      const vehicles: Vehicle[] = await res.json();
      const vehicle = vehicles.find((v) => v.slug === slug);
      if (vehicle) return { title: vehicle.name };
    }
  } catch {
    // Fall through: a title fetch failure must never 500 the page.
  }
  return { title: "Our Fleet" };
}

export default function FleetDetailPage() {
  return <FleetDetailClient />;
}
