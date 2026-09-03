import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 900: "#0b0f14", 800: "#11161d", 700: "#182029", 600: "#222b36", 500: "#2d3947" },
        pos: "#3ddc97",
        neg: "#ff6b6b",
        warn: "#ffc857",
        muted: "#8b98a8",
      },
      fontFamily: { mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
    },
  },
  plugins: [],
};

export default config;
