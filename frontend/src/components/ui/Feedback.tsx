"use client";
import { useEffect, useState } from "react";
export default function Feedback() {
  const [message, setMessage] = useState("");
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const receive = (event: Event) => {
      setMessage((event as CustomEvent<string>).detail);
      clearTimeout(timer); timer = setTimeout(() => setMessage(""), 6000);
    };
    window.addEventListener("client-feedback", receive);
    return () => { clearTimeout(timer); window.removeEventListener("client-feedback", receive); };
  }, []);
  return <div role="status" aria-live="polite" className={message ? "mm-toast" : ""}>{message}</div>;
}
