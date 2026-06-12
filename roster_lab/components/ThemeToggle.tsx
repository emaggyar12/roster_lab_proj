"use client";

import type React from "react";
import { useEffect, useState } from "react";
import clsx from "clsx";
import { Laptop, Moon, Sun } from "lucide-react";

type ThemeMode = "system" | "light" | "dark";

const STORAGE_KEY = "roster-lab-theme";

const modes: Array<{ mode: ThemeMode; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { mode: "system", label: "System", icon: Laptop },
  { mode: "light", label: "Light", icon: Sun },
  { mode: "dark", label: "Dark", icon: Moon },
];

export function ThemeToggle() {
  const [mode, setMode] = useState<ThemeMode>("system");

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") {
      setMode(stored);
      applyTheme(stored);
      return;
    }
    applyTheme("system");
  }, []);

  useEffect(() => {
    if (mode !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = () => applyTheme("system");
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, [mode]);

  function chooseMode(nextMode: ThemeMode) {
    setMode(nextMode);
    window.localStorage.setItem(STORAGE_KEY, nextMode);
    applyTheme(nextMode);
  }

  return (
    <div className="grid grid-cols-3 rounded border border-white/10 bg-white/5 p-1">
      {modes.map((item) => {
        const Icon = item.icon;
        const active = item.mode === mode;
        return (
          <button
            key={item.mode}
            type="button"
            onClick={() => chooseMode(item.mode)}
            className={clsx(
              "flex h-8 items-center justify-center gap-1.5 rounded px-2 text-xs font-semibold transition",
              active ? "bg-[#ffffff] text-[#17202a]" : "text-slate-300 hover:bg-white/10 hover:text-white",
            )}
            title={`${item.label} theme`}
          >
            <Icon className="h-3.5 w-3.5" />
            <span className="hidden xl:inline">{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}

export function applyTheme(mode: ThemeMode) {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const shouldUseDark = mode === "dark" || (mode === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", shouldUseDark);
  document.documentElement.dataset.theme = mode;
}
