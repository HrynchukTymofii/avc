"use client";

import {
  ClapperboardIcon,
  FilmIcon,
  ImageIcon,
  LayoutGridIcon,
  MicIcon,
  PaletteIcon,
  PersonStandingIcon,
  ScanFaceIcon,
  SparklesIcon,
  UserRoundIcon,
  Wand2Icon,
  ZapIcon,
} from "lucide-react";
import { signOut, useSession } from "next-auth/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { AUTH_ENABLED, getCredits } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { CreditsResponse } from "@/types/api";

type NavIcon = React.ComponentType<{ className?: string }>;

interface NavItem {
  label: string;
  desc: string;
  href: string;
  icon: NavIcon;
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
    items: [
      {
        label: "Voice Over Studio",
        desc: "Narration with an S2 Pro voice clone",
        href: "/voice",
        icon: MicIcon,
      },
    ],
  },
  {
    label: "Video",
    href: "/talking-head",
    paths: ["/talking-head", "/broll", "/full-video"],
    items: [
      {
        label: "Full Video",
        desc: "Tagged script → finished video with scenes",
        href: "/full-video",
        icon: ClapperboardIcon,
      },
      {
        label: "Talking Head",
        desc: "Lip-sync a portrait to your script",
        href: "/talking-head?model=musetalk",
        icon: UserRoundIcon,
      },
      {
        label: "Talking Head — Animated",
        desc: "Idle motion + lip-sync, more alive",
        href: "/talking-head?model=musetalk-animate",
        icon: ScanFaceIcon,
      },
      {
        label: "Full Motion (S2V 14B)",
        desc: "Full-body talking video",
        href: "#",
        icon: SparklesIcon,
        premium: true,
      },
      {
        label: "B-Roll",
        desc: "Short AI clips from a prompt — Wan2.2 5B",
        href: "/broll?model=wan-5b",
        icon: FilmIcon,
      },
      {
        label: "B-Roll — A14B",
        desc: "Higher quality motion",
        href: "#",
        icon: FilmIcon,
        premium: true,
      },
      {
        label: "Character Video",
        desc: "Animate a character — Animate 14B",
        href: "#",
        icon: PersonStandingIcon,
        premium: true,
      },
      {
        label: "Upscale Video",
        desc: "Sharpen and enlarge with Real-ESRGAN",
        href: "/upscale?media=video",
        icon: Wand2Icon,
      },
    ],
  },
  {
    label: "Image",
    href: "/image",
    paths: ["/image"],
    items: [
      {
        label: "Wan2.2 5B",
        desc: "Single frame from the video model",
        href: "/image?model=wan-5b",
        icon: ImageIcon,
      },
      {
        label: "FLUX.1 schnell",
        desc: "Fast high-quality stills",
        href: "/image?model=flux-schnell",
        icon: ZapIcon,
      },
      {
        label: "Upscale Image",
        desc: "Sharpen and enlarge with Real-ESRGAN",
        href: "/upscale?media=image",
        icon: Wand2Icon,
      },
    ],
  },
  {
    label: "Styles",
    href: "/lora",
    paths: ["/lora"],
    items: [
      {
        label: "Style Lab",
        desc: "Train a LoRA style on your own images",
        href: "/lora",
        icon: PaletteIcon,
      },
    ],
  },
  {
    label: "Library",
    href: "/library",
    paths: ["/library"],
    items: [
      {
        label: "All generations",
        desc: "Play, download, regenerate, upscale, delete",
        href: "/library",
        icon: LayoutGridIcon,
      },
    ],
  },
];

export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-6 rounded-b-xl border-x border-b bg-background/70 pl-6 pr-3 shadow-lg shadow-black/30 backdrop-blur-xl">
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
                  "inline-block rounded-md px-3.5 py-1.5 font-mono text-xs uppercase tracking-widest transition-colors",
                  group.paths.includes(pathname)
                    ? "bg-primary/15 text-foreground"
                    : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                )}
              >
                {group.label}
              </Link>
              {/* pt-2 bridges the gap to the bar so hover survives the trip */}
              <div className="invisible absolute left-0 top-full z-50 pt-2 opacity-0 transition-opacity duration-100 group-hover:visible group-hover:opacity-100">
                <div className="w-80 rounded-xl border bg-popover/95 p-2 shadow-xl shadow-black/40 backdrop-blur-xl">
                  {group.items.map((item) => {
                    const Icon = item.icon;
                    const row = (
                      <>
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-secondary/60">
                          <Icon className="size-4" />
                        </span>
                        <span className="min-w-0">
                          <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                            <span className="truncate">{item.label}</span>
                            {item.premium && (
                              <span className="shrink-0 rounded border px-1.5 py-px font-mono text-[8px] uppercase tracking-wider text-muted-foreground">
                                premium
                              </span>
                            )}
                          </span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {item.desc}
                          </span>
                        </span>
                      </>
                    );
                    return item.premium ? (
                      <div
                        key={item.label}
                        className="flex cursor-default items-center gap-3 rounded-lg px-2 py-2 opacity-55"
                      >
                        {row}
                      </div>
                    ) : (
                      <Link
                        key={item.label}
                        href={item.href}
                        className="flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-secondary"
                      >
                        {row}
                      </Link>
                    );
                  })}
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
          className="inline-block rounded-lg bg-primary/15 px-4 py-1.5 font-mono text-xs uppercase tracking-widest text-foreground transition-colors hover:bg-primary/25"
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
        className="flex items-center gap-2.5 rounded-lg border bg-secondary/60 py-1 pl-1 pr-4 transition-colors hover:bg-secondary"
      >
        <span className="flex size-7 items-center justify-center rounded-md bg-linear-to-b from-primary to-[oklch(0.52_0.18_262)]">
          <UserRoundIcon className="size-3.5 text-primary-foreground" />
        </span>
        <span className="hidden text-left sm:block">
          <span className="block max-w-32 truncate text-xs text-foreground/90">{name}</span>
          <span className="block font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
            {creditsLabel}
          </span>
        </span>
      </button>
      <div className="invisible absolute right-0 top-full z-50 pt-2 opacity-0 transition-opacity duration-100 group-hover:visible group-hover:opacity-100">
        <div className="min-w-48 rounded-xl border bg-popover/95 p-1.5 shadow-xl shadow-black/40 backdrop-blur-xl">
          <div className="px-3 py-2">
            <p className="truncate text-xs text-foreground/90">{name}</p>
            <p className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              {creditsLabel}
            </p>
          </div>
          <Link
            href="/library"
            className="block rounded-lg px-3 py-2 text-xs text-foreground/90 transition-colors hover:bg-secondary"
          >
            My library
          </Link>
          {AUTH_ENABLED && session?.user && (
            <button
              type="button"
              onClick={() => signOut({ callbackUrl: "/sign-in" })}
              className="block w-full rounded-lg px-3 py-2 text-left text-xs text-foreground/90 transition-colors hover:bg-secondary"
            >
              Sign out
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
