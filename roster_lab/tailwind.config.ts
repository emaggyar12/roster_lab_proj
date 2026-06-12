import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "rgb(var(--color-ink) / <alpha-value>)",
        muted: "rgb(var(--color-muted) / <alpha-value>)",
        page: "rgb(var(--color-page) / <alpha-value>)",
        panel: "rgb(var(--color-panel) / <alpha-value>)",
        surface: "rgb(var(--color-surface) / <alpha-value>)",
        court: "#d88f45",
        line: "rgb(var(--color-line) / <alpha-value>)",
      },
      boxShadow: {
        soft: "0 10px 30px rgba(23, 32, 42, 0.08)",
      },
    },
  },
  plugins: [],
};

export default config;
