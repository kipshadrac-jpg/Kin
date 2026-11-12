import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import { RegisterSW } from "@/components/RegisterSW";
import "./globals.css";

const jakarta = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-jakarta", display: "swap" });
const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || "Kin";

export const metadata: Metadata = {
  title: APP_NAME,
  description: "A personal companion for habits, money decisions and daily life.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon-192.png", apple: "/icon-192.png" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#eef2eb" },
    { media: "(prefers-color-scheme: dark)", color: "#111915" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={jakarta.variable}>
      <body className="min-h-dvh bg-bg font-sans text-ink antialiased">
        {children}
        <RegisterSW />
      </body>
    </html>
  );
}
