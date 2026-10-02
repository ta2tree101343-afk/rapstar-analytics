import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: {
          base: "#0B0B0F",
          card: "#14141B",
          elevated: "#1B1B23",
        },
        border: {
          subtle: "#2A2A34",
          strong: "#3B3B47",
        },
        fg: {
          primary: "#E9E9EE",
          secondary: "#9A9AA5",
          muted: "#666673",
        },
        accent: {
          yellow: "#F5B301",
          purple: "#8A6BFF",
        },
        pos: "#3EE07F",
        neg: "#FF6B6B",
      },
      fontFamily: {
        // Latin glyphs come from Inter; Japanese glyphs come from Zen Kaku
        // Gothic New. Zen Kaku must precede the system fallbacks so Japanese
        // characters don't drop through to Hiragino / Yu Gothic UI on
        // different OSes.
        sans: [
          "Inter",
          '"Zen Kaku Gothic New"',
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "Roboto",
          "sans-serif",
        ],
        // Display face used only for the site name (Latin only — Bebas Neue
        // has no JP glyphs, so it's applied via explicit `font-display`).
        display: ['"Bebas Neue"', "Inter", "sans-serif"],
        mono: ["JetBrains Mono", "SF Mono", "Menlo", "Consolas", "monospace"],
      },
      fontVariantNumeric: {
        tnum: "tabular-nums",
      },
    },
  },
  plugins: [],
} satisfies Config;
