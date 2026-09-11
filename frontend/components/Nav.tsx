"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const LINKS = [
  { href: "/", label: "Board" },
  { href: "/comparison", label: "Comparison" },
  { href: "/audit", label: "Audit" },
] as const;

export function Nav(): ReactNode {
  const pathname = usePathname();

  return (
    <nav className="flex items-center gap-1" aria-label="Console sections">
      {LINKS.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className="nav-link"
          data-active={pathname === link.href ? "true" : "false"}
          aria-current={pathname === link.href ? "page" : undefined}
        >
          {link.label}
        </Link>
      ))}
    </nav>
  );
}
