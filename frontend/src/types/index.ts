// Domain types — hand-written now; replaced by openapi-typescript generated types when Swagger lands

export interface Vehicle {
  id: string;
  slug: string;
  name: string;
  class: string;
  image: string;
  passengers: number;
  luggage: number;
  price: number;
  facilities: string[];
}

export interface Location {
  id: string;
  label: string;
  type: "airport" | "city" | "address";
}

export interface BookingSearch {
  from: Location;
  to: Location;
  date: string;
  time: string;
}

export interface ExtraItem {
  id: string;
  label: string;
  qty: number;
  priceEach: number;
}

export interface PassengerDetails {
  name: string;
  lastName: string;
  email: string;
  phone: string;
  passengers: number;
  luggage: number;
  notes?: string;
}

export interface BillingDetails {
  name: string;
  lastName: string;
  company?: string;
  address: string;
  country: string;
  city: string;
  zip: string;
}

export interface PaymentDetails {
  method: "card" | "paypal";
  billing: BillingDetails;
}

export interface Booking {
  id: string;
  status: "pending" | "confirmed" | "cancelled";
  search: BookingSearch;
  vehicle: Vehicle;
  extras: { items: ExtraItem[]; trainNo?: string; notes?: string };
  passenger: PassengerDetails;
  totalPrice: number;
  createdAt: string;
}

export interface Service {
  id: string;
  slug: string;
  title: string;
  description: string;
  image: string;
  icon: string;
}

export interface Post {
  id: string;
  slug: string;
  title: string;
  excerpt: string;
  image: string;
  date: string;
  category: string;
  author: string;
}

export interface TeamMember {
  id: string;
  slug: string;
  name: string;
  role: string;
  image: string;
  bio?: string;
}

export interface PricingTier {
  id: string;
  name: string;
  price: number;
  period: "trip" | "hour" | "day";
  features: string[];
  highlighted?: boolean;
}

export interface User {
  id: string;
  name: string;
  email: string;
  phone?: string;
}

export interface ApiError {
  message: string;
  code?: string;
  field?: string;
}
