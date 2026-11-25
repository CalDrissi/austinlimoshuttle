"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";

/**
 * Each booking step starts at the top of the page — on phones the next step
 * otherwise opens mid-scroll where the previous CTA was. Browser back/forward
 * is exempt: restoring the old scroll position is exactly what back means.
 */
export default function StepScrollReset() {
  const pathname = usePathname();
  const popped = useRef(false);

  useEffect(() => {
    const onPop = () => { popped.current = true; };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    if (popped.current) { popped.current = false; return; }
    window.scrollTo(0, 0);
  }, [pathname]);

  return null;
}
