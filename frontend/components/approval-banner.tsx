"use client";

import { useSession } from "next-auth/react";

import { AUTH_ENABLED } from "@/lib/api";

/** Shown to signed-in but not-yet-approved accounts: they can browse, but the
 * backend rejects job submissions until an admin flips the flag. */
export function ApprovalBanner() {
  const { data: session } = useSession();
  if (!AUTH_ENABLED || !session?.user || session.user.approved) return null;

  return (
    <div className="border-b border-amber-500/30 bg-amber-500/10">
      <p className="mx-auto max-w-6xl px-4 py-2 text-center font-mono text-[11px] uppercase tracking-widest text-amber-500">
        Your account is awaiting approval — generation is disabled until an admin
        enables it
      </p>
    </div>
  );
}
