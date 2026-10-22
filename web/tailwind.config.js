/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#070B14", 900: "#0B1120", 850: "#0F172A", 800: "#131C2E", 700: "#1C2740", 600: "#2A3755" },
        accent: { DEFAULT: "#2DD4BF", soft: "#2DD4BF1F", strong: "#14B8A6" },
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Cascadia Code", "Consolas", "ui-monospace", "monospace"],
      },
      boxShadow: { glow: "0 0 0 1px #2DD4BF33, 0 8px 30px -12px #2DD4BF55" },
    },
  },
  plugins: [],
};
