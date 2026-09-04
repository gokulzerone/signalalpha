import type { Config } from "tailwindcss";

// Colours are exposed as tokens only; components never name a raw hex, so both themes stay
// in step and nothing can be tinted by accident.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ground: "var(--ground)",
        surface: "var(--surface)",
        raised: "var(--raised)",
        ink: { DEFAULT: "var(--ink)", 2: "var(--ink-2)", 3: "var(--ink-3)" },
        rule: { DEFAULT: "var(--rule)", strong: "var(--rule-strong)" },
        link: "var(--link)",
        pos: "var(--pos)",
        neg: "var(--neg)",
        caution: "var(--caution)",
        bar: "var(--bar)",
      },
      fontFamily: {
        sans: ["Archivo", "ui-sans-serif", "system-ui", "sans-serif"],
        serif: ["Source Serif 4", "Georgia", "serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "Menlo", "monospace"],
      },
      maxWidth: { measure: "68ch" },
      boxShadow: { card: "var(--shadow)" },
    },
  },
  plugins: [],
};

export default config;
