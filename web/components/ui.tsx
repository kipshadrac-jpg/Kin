"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "outline" | "ghost" | "soft";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const styles: Record<Variant, string> = {
    primary: "bg-ink text-on-ink",
    outline: "border-2 border-line bg-surface text-ink",
    ghost: "text-muted",
    soft: "bg-surface text-ink",
  };
  return (
    <button
      {...props}
      className={`min-h-12 rounded-2xl px-5 text-[17px] font-medium transition active:scale-[.98] ${styles[variant]} ${className}`}
    />
  );
}

export function Card({ children, tone = "white", className = "" }: { children: ReactNode; tone?: "white" | "soft"; className?: string }) {
  return (
    <section className={`rounded-[28px] p-5 ${tone === "soft" ? "bg-soft" : "bg-surface"} ${className}`}>{children}</section>
  );
}

export function Chip({ children, active = false, onClick }: { children: ReactNode; active?: boolean; onClick?: () => void }) {
  const cls = `inline-flex min-h-10 items-center rounded-full px-4 text-[15px] ${
    active ? "bg-ink text-on-ink" : "bg-surface text-ink border border-line"
  }`;
  return onClick ? (
    <button type="button" onClick={onClick} className={cls} aria-pressed={active}>
      {children}
    </button>
  ) : (
    <span className={cls}>{children}</span>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="text-[15px] tracking-wide text-muted">{children}</p>;
}

export function Title({ children }: { children: ReactNode }) {
  return <h1 className="mt-1 text-[32px] font-bold leading-tight tracking-tight">{children}</h1>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[15px] font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-sm text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "w-full min-h-12 rounded-2xl border border-line px-4 py-3 text-[17px] placeholder:text-muted/70 focus:border-ink";

export function Note({ children }: { children: ReactNode }) {
  return <p className="text-[15px] text-muted">{children}</p>;
}

export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <p role="alert" className="text-[15px] text-danger">
      {children}
    </p>
  );
}

const TABS = [
  { href: "/", label: "Today" },
  { href: "/think/", label: "Think" },
  { href: "/money/", label: "Money" },
  { href: "/me/", label: "Me" },
];

export function BottomNav() {
  const path = usePathname() || "/";
  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 rounded-t-[28px] bg-surface pb-[max(env(safe-area-inset-bottom),12px)] pt-3 shadow-[0_-4px_20px_rgba(0,0,0,.04)]">
      <ul className="mx-auto grid max-w-xl grid-cols-4 gap-2 px-3">
        {TABS.map((t) => {
          const active = t.href === "/" ? path === "/" : path.startsWith(t.href);
          return (
            <li key={t.href}>
              <Link
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-12 items-center justify-center rounded-2xl text-[17px] ${
                  active ? "bg-ink font-medium text-on-ink" : "text-muted"
                }`}
              >
                {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function Page({ children }: { children: ReactNode }) {
  return <main className="mx-auto max-w-xl px-5 pb-32 pt-12 sm:pt-16">{children}</main>;
}
