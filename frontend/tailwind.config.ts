import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", '"Noto Sans Thai"', '"Segoe UI"', "sans-serif"],
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
          available: "#16A34A",
          borrowed: "#2563EB",
          pm: "#CA8A04",
          calibration: "#7C3AED",
          repair: "#EA580C",
          out_of_service: "#6B7280",
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
