import type { Metadata } from "next";
import Script from "next/script";
import { DM_Sans } from "next/font/google";
import { Providers } from "@/providers/Providers";

// Swiper CSS (no relative image urls — safe as JS import)
import "swiper/css";
import "swiper/css/navigation";
import "swiper/css/pagination";

// Self-hosted by next/font — the SWC compiler works now, so the Babel fallback
// and its CDN <link> are both gone. That also keeps the page within a
// script-src 'self' policy.
const dmSans = DM_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  display: "swap",
  variable: "--font-dm-sans",
});

export const metadata: Metadata = {
  title: {
    default: "M&M Austin Limousine — Airport Transfers & Chauffeur Service",
    template: "%s | M&M Austin Limousine",
  },
  description:
    "Private car, limousine and airport shuttle service in Austin, Texas. "
    + "Book online for a fixed fare quoted before you pay.",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon-32.png", type: "image/png", sizes: "32x32" },
      { url: "/favicon-16.png", type: "image/png", sizes: "16x16" },
    ],
    apple: "/apple-touch-icon.png",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" id="top" className={dmSans.variable}>
      <head>
        {/* Vendor CSS — served as static files so relative url() paths resolve correctly */}
        <link rel="stylesheet" href="/assets/css/vendors/normalize.css" />
        <link rel="stylesheet" href="/assets/css/vendors/bootstrap.min.css" />
        <link rel="stylesheet" href="/assets/css/vendors/uicons-regular-rounded.css" />
        <link rel="stylesheet" href="/assets/css/vendors/animate.css" />
        {/* Main Luxride stylesheet — must come last so it wins */}
        <link rel="stylesheet" href="/assets/css/luxride.css" />
        {/* Project overrides — loaded after luxride.css so they win. */}
        <link rel="stylesheet" href="/assets/css/custom.css" />
      </head>
      <body>
        <div className="body-overlay-1" />
        <Providers>
          {children}
        </Providers>
        {/* Bootstrap 5 bundle (vanilla JS) powers the template's accordion +
            dropdown toggles (FAQs, fleet filters). Loaded after hydration. */}
        <Script src="/assets/js/vendors/bootstrap.bundle.min.js" strategy="afterInteractive" />
      </body>
    </html>
  );
}
