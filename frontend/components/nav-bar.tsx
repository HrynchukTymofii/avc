"use client";

import { UserRoundIcon } from "lucide-react";
import { signOut, useSession } from "next-auth/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { AUTH_ENABLED, getCredits } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { CreditsResponse } from "@/types/api";

interface NavItem {
  label: string;
  href: string;
  premium?: boolean;
}

interface NavGroup {
  label: string;
  href: string;
  /** pathnames that highlight this group */
  paths: string[];
  items: NavItem[];
}

const GROUPS: NavGroup[] = [
  {
    label: "Voice Over",
    href: "/voice",
    paths: ["/voice"],
    items: [{ label: "Narration — S2 Pro voice clone", href: "/voice" }],
  },
  {
    label: "Video",
    href: "/talking-head",
    paths: ["/talking-head", "/broll", "/full-video"],
    items: [
      { label: "Full video — tagged script assembler", href: "/full-video" },
      { label: "Talking head — lip-sync", href: "/talking-head?model=musetalk" },
      { label: "Talking head — animated", href: "/talking-head?model=musetalk-animate" },
      { label: "Talking head — full motion (S2V 14B)", href: "#", premium: true },
      { label: "B-roll — Wan2.2 5B", href: "/broll?model=wan-5b" },
      { label: "B-roll — A14B high quality", href: "#", premium: true },
      { label: "Character video — Animate 14B", href: "#", premium: true },
      { label: "Upscale video — Real-ESRGAN", href: "/upscale" },
    ],
  },
  {
    label: "Image",
    href: "/image",
    paths: ["/image"],
    items: [
      { label: "Wan2.2 5B — single frame", href: "/image?model=wan-5b" },
      { label: "FLUX.1 schnell", href: "/image?model=flux-schnell" },
      { label: "Upscale image — Real-ESRGAN", href: "/upscale" },
    ],
  },
  {
    label: "Styles",
    href: "/lora",
    paths: ["/lora"],
    items: [{ label: "Style Lab — train a LoRA on your images", href: "/lora" }],
  },
  {
    label: "Library",
    href: "/library",
    paths: ["/library"],
    items: [
      { label: "All generations — play, regenerate, upscale, delete", href: "/library" },
    ],
  },
];

export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-6 rounded-b-3xl border-x border-b bg-background/70 pl-6 pr-3 shadow-lg shadow-black/30 backdrop-blur-xl">
        <Link href="/talking-head" className="flex items-center gap-2.5">
          <span className="rec-dot" aria-hidden />
          <span className="font-heading text-[15px] font-semibold tracking-tight">
            AI Video Studio
          </span>
        </Link>
        <nav className="flex items-center gap-1">
          {GROUPS.map((group) => (
            <div key={group.label} className="group relative">
              <Link
                href={group.href}
                className={cn(
                  "inline-block rounded-full px-3.5 py-1.5 font-mono text-xs uppercase tracking-widest transition-colors",
                  group.paths.includes(pathname)
                    ? "bg-primary/15 text-foreground"
                    : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                )}
              >
                {group.label}
              </Link>
              {/* pt-3 bridges the gap to the floating bar so hover survives the trip */}
              <div className="invisible absolute left-0 top-full z-50 pt-3 opacity-0 transition-opacity duration-100 group-hover:visible group-hover:opacity-100">
                <div className="min-w-64 rounded-2xl border bg-popover/90 p-1.5 shadow-xl shadow-black/30 backdrop-blur-xl">
                  {group.items.map((item) =>
                    item.premium ? (
                      <div
                        key={item.label}
                        className="flex cursor-default items-center justify-between gap-3 rounded-xl px-3 py-2 text-xs text-muted-foreground/60"
                      >
                        <span>{item.label}</span>
                        <span className="shrink-0 rounded-full border px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider">
                          premium
                        </span>
                      </div>
                    ) : (
                      <Link
                        key={item.label}
                        href={item.href}
                        className="block rounded-xl px-3 py-2 text-xs text-foreground/90 transition-colors hover:bg-secondary"
                      >
                        {item.label}
                      </Link>
                    ),
                  )}
                </div>
              </div>
            </div>
          ))}
        </nav>
        <AccountMenu />
      </div>
    </header>
  );
}

function AccountMenu() {
  const { data: session, status } = useSession();
  const userId = session?.user?.userId;
  const [credits, setCredits] = useState<CreditsResponse | null>(null);
  useEffect(() => {
    // Works without accounts too — the backend reports the local session then.
    if (AUTH_ENABLED && !userId) return;
    getCredits()
      .then(setCredits)
      .catch(() => setCredits(null));
  }, [userId]);

  if (AUTH_ENABLED && status === "loading") return null;

  if (AUTH_ENABLED && !session?.user) {
    return (
      <div className="ml-auto">
        <Link
          href="/sign-in"
          className="inline-block rounded-full bg-primary/15 px-4 py-1.5 font-mono text-xs uppercase tracking-widest text-foreground transition-colors hover:bg-primary/25"
        >
          Sign in
        </Link>
      </div>
    );
  }

  const name = session?.user?.name || session?.user?.email || "Local session";
  const creditsLabel =
    credits === null
      ? "…"
      : credits.unlimited
        ? "unlimited"
        : `${credits.balance} credits`;

  return (
    <div className="group relative ml-auto">
      <button
        type="button"
        className="flex items-center gap-2.5 rounded-full border bg-secondary/60 py-1 pl-1 pr-4 transition-colors hover:bg-secondary"
      >
        <span className="flex size-7 items-center justify-center rounded-full bg-linear-to-b from-primary to-[oklch(0.52_0.18_262)]">
          <UserRoundIcon className="size-3.5 text-primary-foreground" />
        </span>
        <span className="hidden text-left sm:block">
          <span className="block max-w-32 truncate text-xs text-foreground/90">{name}</span>
          <span className="block font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
            {creditsLabel}
          </span>
        </span>
      </button>
      <div className="invisible absolute right-0 top-full z-50 pt-3 opacity-0 transition-opacity duration-100 group-hover:visible group-hover:opacity-100">
        <div className="min-w-48 rounded-2xl border bg-popover/90 p-1.5 shadow-xl shadow-black/30 backdrop-blur-xl">
          <div className="px-3 py-2">
            <p className="truncate text-xs text-foreground/90">{name}</p>
            <p className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              {creditsLabel}
            </p>
          </div>
          <Link
            href="/library"
            className="block rounded-xl px-3 py-2 text-xs text-foreground/90 transition-colors hover:bg-secondary"
          >
            My library
          </Link>
          {AUTH_ENABLED && session?.user && (
            <button
              type="button"
              onClick={() => signOut({ callbackUrl: "/sign-in" })}
              className="block w-full rounded-xl px-3 py-2 text-left text-xs text-foreground/90 transition-colors hover:bg-secondary"
            >
              Sign out
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
