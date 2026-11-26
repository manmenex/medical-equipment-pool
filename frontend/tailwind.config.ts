import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", '"Noto Sans Thai"', '"Segoe UI"', "sans-serif"],
      },
      // Larger type scale for legibility (owner feedback 2026-11): body-size
      // "sm" text is 15px and the smallest "xs" caption is 13px.
      fontSize: {
        xs: ["0.8125rem", { lineHeight: "1.25rem" }],
        sm: ["0.9375rem", { lineHeight: "1.4rem" }],
      },
      colors: {
        // Roadmap PR6: 4-state equipment model. These tokens double as
        // generic UI accents elsewhere in the app (e.g. "borrowed" = the
        // app's primary accent, "repair" = the error accent) and "pm"/
        // "calibration" remain in use by DashboardPage's pre-existing,
        // out-of-PR6-scope PM/Calibration due-soon cards (pm_due_date/
        // cal_due_date, unrelated to equipment.status) -- kept as the
        // original names rather than renamed to the new status values, so
        // unrelated chrome doesn't need to change. Only the retired
        // status-only keys (cleaning, lost) are removed -- no active
        // status or other UI element maps to them anymore.
        status: {
          available: "#15803D",
          borrowed: "#1D4ED8",
          pm: "#A16207",
          calibration: "#6D28D9",
          repair: "#C2410C",
          out_of_service: "#4B5563",
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
