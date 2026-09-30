import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "AI Web Agency Agent — Owner Dashboard",
  description:
    "Semi-autonomous AI system for lead research, outreach, and website generation. Owner control center.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} font-sans antialiased bg-[#0A0B0F] text-white`}>
        {children}
      </body>
    </html>
  );
}
