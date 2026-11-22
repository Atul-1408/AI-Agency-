import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="en" className="dark" data-scroll-behavior="smooth">
      <body
        className="font-sans antialiased bg-[#0B0A0C] text-[#F5F1EA]"
      >
        {children}
      </body>
    </html>
  );
}

