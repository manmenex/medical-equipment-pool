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
        status: {
          available: "#16A34A",
          borrowed: "#2563EB",
          cleaning: "#0EA5E9",
          pm: "#CA8A04",
          calibration: "#7C3AED",
          repair: "#EA580C",
          out_of_service: "#6B7280",
          lost: "#DC2626",
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
