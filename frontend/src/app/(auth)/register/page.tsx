"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { clientDestination } from "@/lib/feedback";
import { RegisterFields } from "@/components/auth/AuthForms";

function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = clientDestination(params.get("next"));

  return (
    <section className="section pt-80 pb-80">
      <div className="container" style={{ maxWidth: 460 }}>
        <h2 className="heading-36-medium mb-10">Create your account</h2>
        <p className="text-14 color-grey mb-30">
          Already have one? <Link href={`/login?next=${encodeURIComponent(next)}`}>Sign in</Link>
        </p>
        <RegisterFields initialEmail={params.get("email") || ""} onSuccess={() => router.push(next)} />
      </div>
    </section>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterForm />
    </Suspense>
  );
}
