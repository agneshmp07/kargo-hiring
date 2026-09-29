import type { Metadata } from "next";
import { Fraunces, Outfit, Plus_Jakarta_Sans, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { ToastProvider } from "@/components/ui";

// Each theme picks its own pair of fonts from these (see globals.css).
const jakarta = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--f-jakarta", display: "swap" });
const space = Space_Grotesk({ subsets: ["latin"], variable: "--f-space", display: "swap" });
const fraunces = Fraunces({ subsets: ["latin"], variable: "--f-fraunces", display: "swap", axes: ["opsz"] });
const outfit = Outfit({ subsets: ["latin"], variable: "--f-outfit", display: "swap" });

export const metadata: Metadata = {
  title: "Kargo hiring",
  description: "The system recommends. You decide.",
  robots: { index: false, follow: false },
};

// Apply the saved theme before the first paint, so the page never flashes the wrong look.
const themeScript = `try{var t=localStorage.getItem("kargo-theme");if(t)document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="harbour" suppressHydrationWarning
      className={`${jakarta.variable} ${space.variable} ${fraunces.variable} ${outfit.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="font-sans">
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
