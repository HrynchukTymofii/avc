import type { Metadata } from "next";
import { Bricolage_Grotesque, Geist, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

import { ApprovalBanner } from "@/components/approval-banner";
import { NavBar } from "@/components/nav-bar";
import { Providers } from "@/components/providers";

const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-mono-plex",
  weight: ["400", "500"],
  subsets: ["latin"],
});

const bricolage = Bricolage_Grotesque({
  variable: "--font-display",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI Video Studio",
  description: "Talking-head videos and AI B-roll on your own GPU",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`dark ${geistSans.variable} ${plexMono.variable} ${bricolage.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <Providers>
          <NavBar />
          <ApprovalBanner />
          <main className="w-full max-w-6xl flex-1 mx-auto px-4 py-10">{children}</main>
          <footer className="border-t py-4">
            <p className="mx-auto max-w-6xl px-4 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              One GPU &middot; one job at a time &middot; queued jobs run in order
            </p>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
