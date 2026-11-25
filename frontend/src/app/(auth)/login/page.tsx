"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { clientDestination } from "@/lib/feedback";
import { LoginFields } from "@/components/auth/AuthForms";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = clientDestination(params.get("next"));

  return (
    <section className="section pt-80 pb-80">
      <div className="container" style={{ maxWidth: 440 }}>
        <h2 className="heading-36-medium mb-10">Sign in</h2>
        <p className="text-14 color-grey mb-30">
          New here? <Link href={`/register?next=${encodeURIComponent(next)}`}>Create an account</Link>
        </p>
        <LoginFields onSuccess={() => router.push(next)} />

        {next.startsWith("/booking") && (
          <>
            <div className="text-14 color-grey" style={{ textAlign: "center", margin: "18px 0" }}>— or —</div>
            <button className="btn btn-white hover-up w-100" type="button" onClick={() => router.push(next)}>
              Continue as guest
            </button>
            <p className="text-13 color-grey mt-10" style={{ textAlign: "center" }}>
              No account needed — you&apos;ll get a receipt by email.
            </p>
          </>
        )}
      </div>
    </section>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
