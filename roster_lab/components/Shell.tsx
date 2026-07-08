"use client";

import type React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { BarChart3, ClipboardList, FlaskConical, Github, Linkedin, Mail, Menu, Users } from "lucide-react";
import { useState } from "react";
import { ThemeToggle } from "@/components/ThemeToggle";

const navItems = [
  { href: "/players", label: "Players", icon: BarChart3 },
  { href: "/rosters", label: "Roster Management", icon: ClipboardList },
  { href: "/optimizer", label: "Optimizer", icon: FlaskConical },
  { href: "/teams", label: "Teams", icon: Users },
];

const emailAddress = "aharsha@vols.utk.edu";

const socialLinks = [
  { href: "https://www.linkedin.com/in/anirudhha-harsha-0103a0251/", label: "LinkedIn", icon: Linkedin },
  { href: "https://github.com/emaggyar12/roster_lab_proj", label: "GitHub", icon: Github },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [emailCopied, setEmailCopied] = useState(false);

  async function copyEmail() {
    await navigator.clipboard.writeText(emailAddress);
    setEmailCopied(true);
    window.setTimeout(() => setEmailCopied(false), 1600);
  }

  return (
    <div className="min-h-screen bg-page">
      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-20 hidden border-r border-line bg-[#17202a] text-white transition-[width] lg:block",
          collapsed ? "w-20" : "w-60",
        )}
      >
        <div className={clsx("border-b border-white/10 py-5", collapsed ? "px-3" : "px-5")}>
          <div className="flex items-center justify-between gap-3">
            <div className={clsx(collapsed && "sr-only")}>
              <div className="text-lg font-semibold">Roster Lab</div>
              <div className="mt-1 text-xs text-slate-300">Recruiting operations</div>
            </div>
            <button
              type="button"
              onClick={() => setCollapsed((value) => !value)}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded border border-white/10 bg-white/5 text-slate-200 hover:bg-white/10"
              title={collapsed ? "Open sidebar" : "Collapse sidebar"}
            >
              <Menu className="h-5 w-5" />
            </button>
          </div>
        </div>
        <nav className="space-y-1 px-3 py-4">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={clsx(
                  "flex h-10 items-center gap-3 rounded px-3 text-sm font-medium transition",
                  collapsed && "justify-center",
                  active
                    ? "bg-[#f8faf7] text-[#17202a] dark:bg-slate-700 dark:text-white"
                    : "text-slate-200 hover:bg-white/10 hover:text-white",
                )}
                title={item.label}
              >
                <Icon className="h-4 w-4" />
                <span className={clsx(collapsed && "sr-only")}>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        {!collapsed ? (
          <div className="absolute bottom-0 left-0 right-0 space-y-3 border-t border-white/10 p-3">
            <div className="relative flex items-center justify-center gap-3">
              {emailCopied ? (
                <div className="absolute -top-9 rounded border border-white/10 bg-[#f8faf7] px-3 py-1 text-xs font-semibold text-[#17202a] shadow-lg">
                  Email copied!
                </div>
              ) : null}
              <button
                type="button"
                onClick={copyEmail}
                aria-label="Copy email"
                title="Copy email"
                className="flex h-9 w-9 items-center justify-center rounded border border-white/10 bg-white/5 text-slate-300 transition hover:border-white/20 hover:bg-white/10 hover:text-white"
              >
                <Mail className="h-4.5 w-4.5" />
              </button>
              {socialLinks.map((item) => {
                const Icon = item.icon;

                return (
                  <a
                    key={item.href}
                    href={item.href}
                    aria-label={item.label}
                    title={item.label}
                    target="_blank"
                    rel="noreferrer"
                    className="flex h-9 w-9 items-center justify-center rounded border border-white/10 bg-white/5 text-slate-300 transition hover:border-white/20 hover:bg-white/10 hover:text-white"
                  >
                    <Icon className="h-4.5 w-4.5" />
                  </a>
                );
              })}
            </div>
            <ThemeToggle />
          </div>
        ) : null}
      </aside>

      <div className={clsx("transition-[padding-left]", collapsed ? "lg:pl-20" : "lg:pl-60")}>
        <header className="sticky top-0 z-10 border-b border-line bg-panel/95 px-4 py-3 backdrop-blur lg:hidden">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="text-lg font-semibold text-ink">Roster Lab</div>
            <div className="rounded bg-[#17202a] p-1">
              <ThemeToggle />
            </div>
          </div>
          <nav className="flex gap-2 overflow-x-auto">
            {navItems.map((item) => {
              const Icon = item.icon;
              const active = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={clsx(
                    "flex h-9 shrink-0 items-center gap-2 rounded border px-3 text-sm font-medium",
                    active
                      ? "border-emerald-600 bg-emerald-600 text-white dark:border-emerald-400 dark:bg-emerald-500 dark:text-slate-950"
                      : "border-line bg-white text-slate-700",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6 md:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
