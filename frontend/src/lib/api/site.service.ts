import { USE_MOCKS } from "./config";
import { apiGet } from "./client";

/**
 * Site-wide contact details and social links.
 *
 * Read from the backend rather than hardcoded so the office can change a phone
 * number in the dashboard without a deploy. Every field may legitimately be
 * empty — callers must render nothing rather than a dead `#` link.
 */
export interface SiteSettings {
  contact_email: string;
  contact_phone: string;
  facebook: string;
  instagram: string;
  twitter: string;
  linkedin: string;
  google_maps_api_key: string;
  /** Office minimum booking lead (hours); the widget hides earlier time slots. */
  min_booking_lead_hours: number;
}

const EMPTY: SiteSettings = {
  contact_email: "",
  contact_phone: "",
  facebook: "",
  instagram: "",
  twitter: "",
  linkedin: "",
  google_maps_api_key: "",
  min_booking_lead_hours: 0,
};

const http = {
  // A missing phone number is not worth breaking the header over.
  get: async (): Promise<SiteSettings> => {
    try {
      return await apiGet<SiteSettings>("/site-settings/");
    } catch {
      return EMPTY;
    }
  },
};

const mocks = {
  get: async (): Promise<SiteSettings> => EMPTY,
};

export const siteService = USE_MOCKS ? mocks : http;

/** Strip formatting for a tel: href, keeping a leading +. */
export const telHref = (phone: string) => `tel:${phone.replace(/[^\d+]/g, "")}`;
