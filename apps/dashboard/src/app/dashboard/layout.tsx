import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen overflow-hidden bg-[#0B0A0C] relative selection:bg-[#E8B968]/20 selection:text-[#F5CC7A]">
      {/* Subtle Atmospheric Lighting Overlays (Section 5) */}
      <div
        className="fixed top-0 right-0 w-[850px] h-[500px] pointer-events-none z-0"
        style={{
          background:
            "radial-gradient(circle at 75% 0%, rgba(232, 185, 105, 0.10), transparent 35%)",
        }}
      />
      <div
        className="fixed bottom-0 left-0 w-[750px] h-[480px] pointer-events-none z-0"
        style={{
          background:
            "radial-gradient(circle at 0% 100%, rgba(139, 111, 184, 0.10), transparent 35%)",
        }}
      />

      {/* 260px Left Sidebar */}
      <Sidebar />

      {/* Main Content Area */}
      <div className="flex flex-col flex-1 overflow-hidden relative z-10">
        <Header />

        {/* Scrollable page canvas with 1600px max-width centered constraint */}
        <main className="flex-1 overflow-y-auto px-8 md:px-10 py-8 scrollbar-none animate-fade-in">
          <div className="max-w-[1600px] mx-auto w-full">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
