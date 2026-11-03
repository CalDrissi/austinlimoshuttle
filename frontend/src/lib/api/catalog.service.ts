import { apiGet } from "./client";
import type { Vehicle, Page, Availability } from "@/types/api";

/** Read-only public catalog & CMS content. */
export const catalogService = {
  listVehicles: () => apiGet<Vehicle[]>("/vehicles/"),
  /**
   * A single vehicle class by slug. There's no detail endpoint, so this filters
   * the (small) public list — fine for the fleet detail page.
   */
  getVehicle: async (slug: string): Promise<Vehicle | null> => {
    const vehicles = await apiGet<Vehicle[]>("/vehicles/");
    return vehicles.find((v) => v.slug === slug) ?? null;
  },
  listPages: () => apiGet<Page[]>("/pages/"),
  getPage: (slug: string) => apiGet<Page>(`/pages/${slug}/`),
  availability: () => apiGet<Availability>("/availability/"),
};
