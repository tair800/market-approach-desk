import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

import { MetaStrip } from "@/components/MetaStrip";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "Market approach desk",
  description:
    "Operator console for placing a commercial risk across a carrier panel without approaching the same carrier twice.",
};

export default function RootLayout({ children }: { children: ReactNode }): ReactNode {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="border-b border-[var(--color-line)] bg-[var(--color-panel)]">
          <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-2 px-5 py-2.5">
            <span className="font-semibold tracking-tight">
              Market approach desk
              <span className="text-dim ml-2 font-normal">placement operations</span>
            </span>
            <Nav />
            <span className="ml-auto">
              <MetaStrip />
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-[1600px] px-5 py-5">{children}</main>
      </body>
    </html>
  );
}
