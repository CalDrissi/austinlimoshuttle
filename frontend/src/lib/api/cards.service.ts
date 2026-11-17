import { apiGet, apiPost, apiDelete } from "./client";

/** A card kept on file. Display bits only — never anything to charge with. */
export interface SavedCard {
  id: number;
  brand: string;
  last4: string;
  exp_month: number | null;
  exp_year: number | null;
  is_default: boolean;
  label: string;
  expiry: string;
}

export interface CardSetupIntent {
  client_secret: string;
  publishable_key: string;
}

export const cardsService = {
  list: () => apiGet<SavedCard[]>("/account/cards/"),
  /** Start adding a card: returns a Stripe SetupIntent client secret + key. */
  setupIntent: () => apiPost<CardSetupIntent>("/account/cards/setup-intent/", {}),
  /** Record the card once the browser has confirmed the SetupIntent. */
  save: (payment_method_id: string) =>
    apiPost<SavedCard>("/account/cards/", { payment_method_id }),
  setDefault: (id: number) => apiPost<SavedCard>(`/account/cards/${id}/default/`, {}),
  remove: (id: number) => apiDelete<void>(`/account/cards/${id}/`),
};
