import type { Config } from "tailwindcss";

const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        bg: v("bg"), surface: v("surface"), sunken: v("sunken"), line: v("line"),
        fg: v("fg"), muted: v("muted"), accent: v("accent"), "accent-fg": v("accent-fg"), accent2: v("accent2"),
        good: v("good"), warn: v("warn"), bad: v("bad"), info: v("info"), violet: v("violet"), navy: v("navy"),
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "system-ui", "sans-serif"],
      },
      boxShadow: {
        soft: "0 1px 2px rgb(15 27 45 / 0.04), 0 8px 24px -12px rgb(15 27 45 / 0.18)",
        lift: "0 2px 4px rgb(15 27 45 / 0.06), 0 18px 40px -16px rgb(15 27 45 / 0.30)",
        glow: "0 0 0 1px rgb(var(--accent) / 0.25), 0 10px 30px -10px rgb(var(--accent) / 0.55)",
      },
      keyframes: {
        rise: { "0%": { opacity: "0", transform: "translateY(8px)" }, "100%": { opacity: "1", transform: "none" } },
        pop: { "0%": { transform: "scale(.92)", opacity: "0" }, "60%": { transform: "scale(1.02)", opacity: "1" }, "100%": { transform: "scale(1)" } },
        dash: { to: { strokeDashoffset: "0" } },
        float: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-6px)" } },
        "out-left": { to: { opacity: "0", transform: "translateX(-80px) rotate(-4deg)" } },
        "out-right": { to: { opacity: "0", transform: "translateX(80px) rotate(4deg)" } },
        "out-down": { to: { opacity: "0", transform: "translateY(40px) scale(.97)" } },
        confetti: { "0%": { transform: "translateY(-10vh) rotate(0)", opacity: "1" }, "100%": { transform: "translateY(110vh) rotate(720deg)", opacity: "0.9" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        rise: "rise .45s cubic-bezier(.2,.7,.2,1) both",
        pop: "pop .4s cubic-bezier(.2,.7,.2,1) both",
        float: "float 6s ease-in-out infinite",
        "out-left": "out-left .28s ease-in forwards",
        "out-right": "out-right .28s ease-in forwards",
        "out-down": "out-down .28s ease-in forwards",
      },
    },
  },
  plugins: [],
} satisfies Config;
