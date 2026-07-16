"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

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
    href: "/talking-head?mode=voice",
    paths: [],
    items: [{ label: "Narration — S2 Pro voice clone", href: "/talking-head?mode=voice" }],
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
];

export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 border-b bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-8 px-4">
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
                  "inline-block rounded-md px-3 py-1.5 font-mono text-xs uppercase tracking-widest transition-colors",
                  group.paths.includes(pathname)
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {group.label}
              </Link>
              <div className="invisible absolute left-0 top-full z-50 min-w-64 rounded-md border bg-background p-1 opacity-0 shadow-lg transition-opacity duration-100 group-hover:visible group-hover:opacity-100">
                {group.items.map((item) =>
                  item.premium ? (
                    <div
                      key={item.label}
                      className="flex cursor-default items-center justify-between gap-3 rounded px-3 py-2 text-xs text-muted-foreground/60"
                    >
                      <span>{item.label}</span>
                      <span className="shrink-0 rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider">
                        premium
                      </span>
                    </div>
                  ) : (
                    <Link
                      key={item.label}
                      href={item.href}
                      className="block rounded px-3 py-2 text-xs text-foreground/90 transition-colors hover:bg-secondary"
                    >
                      {item.label}
                    </Link>
                  ),
                )}
              </div>
            </div>
          ))}
        </nav>
      </div>
    </header>
  );
}
