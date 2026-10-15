"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  LayoutGrid,
  Mail,
  CheckSquare,
  Activity,
  Settings,
  Lock,
  Check,
  Circle,
  Sparkles,
  FolderKanban,
} from "lucide-react";

interface NavItem {
  href: string;
  label: string;
  icon: typeof Home;
  locked?: boolean;
  phaseTag?: string;
}

const navItems: NavItem[] = [
  { href: "/dashboard", label: "Overview", icon: Home },
  { href: "/dashboard/leads", label: "Leads", icon: LayoutGrid },
  { href: "/dashboard/outreach", label: "Outreach", icon: Mail },
  { href: "/dashboard/client-intelligence/prds", label: "Client PRDs", icon: FolderKanban },
  { href: "/dashboard/projects", label: "Projects & Builder", icon: Sparkles },
  { href: "/dashboard/approvals", label: "Approvals", icon: CheckSquare },
  { href: "/dashboard/runs", label: "Agent Runs", icon: Activity },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="w-[260px] flex-shrink-0 flex flex-col bg-[#111013] border-r border-[#242126] h-screen select-none relative z-20 overflow-y-auto overflow-x-hidden scrollbar-none"
      style={{ padding: "20px 14px" }}
    >
      {/* 9. Logo Area */}
      <div className="flex items-center gap-3.5 pb-2">
        <div className="w-[44px] h-[44px] rounded-[12px] bg-gradient-to-br from-[#F5CC7A] via-[#E8B968] to-[#A87932] flex items-center justify-center flex-shrink-0 shadow-[0_0_16px_rgba(232,185,105,0.22)] border border-[#F5CC7A]/40">
          <Sparkles className="w-5 h-5 text-[#17130D]" />
        </div>
        <div>
          <h2 className="text-[18px] font-semibold text-[#F5F1EA] tracking-tight leading-tight">
            AI Agency
          </h2>
          <p className="text-[12px] text-[#77717C] font-normal leading-none mt-1">
            Command Center
          </p>
        </div>
      </div>

      <div className="h-[24px] flex-shrink-0" />

      {/* Navigation Items */}
      <nav className="flex flex-col gap-[4px]">
        {navItems.map((item) => {
          const { href, label, icon: Icon, locked, phaseTag } = item;
          const active =
            href === "/dashboard"
              ? pathname === "/dashboard"
              : pathname.startsWith(href);

          if (locked) {
            return (
              <div
                key={href}
                className="h-[42px] px-[12px] rounded-[10px] flex items-center justify-between text-[13px] text-[#77717C] opacity-75 cursor-not-allowed select-none"
                title={`${label} (Upcoming — locked)`}
              >
                <div className="flex items-center gap-[10px]">
                  <Icon size={17} className="text-[#77717C]" />
                  <span>{label}</span>
                </div>
                <div className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-[#171519] border border-[#242126] text-[10px] font-mono text-[#77717C]">
                  <span>{phaseTag ?? "Upcoming"}</span>
                  <Lock size={9} />
                </div>
              </div>
            );
          }

          return (
            <Link
              key={href}
              href={href}
              className={`h-[42px] px-[12px] rounded-[10px] flex items-center justify-between text-[13px] transition-all duration-180 relative ${
                active
                  ? "bg-[rgba(232,185,105,0.12)] text-[#F5F1EA] font-semibold"
                  : "text-[#B7AFBA] hover:text-[#F5F1EA] hover:bg-[#171519]"
              }`}
            >
              {active && (
                <span className="absolute left-0 top-[6px] bottom-[6px] w-[2px] bg-[#E8B968] rounded-r" />
              )}
              <div className="flex items-center gap-[10px]">
                <Icon
                  size={17}
                  className={active ? "text-[#E8B968]" : "text-[#B7AFBA]"}
                />
                <span>{label}</span>
              </div>
            </Link>
          );
        })}
      </nav>

      {/* Flexible Spacer */}
      <div className="flex-1 min-h-[20px]" />

      {/* Phase Progress Card */}
      <div className="relative rounded-[16px] overflow-hidden border border-[#302A30] shadow-2xl group select-none">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/sidebar-mountain.jpg"
          alt="Alpine Horizon"
          className="absolute inset-0 w-full h-full object-cover object-center group-hover:scale-105 transition-transform duration-700 ease-out pointer-events-none"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-[#111013]/60 via-[#111013]/80 to-[#0B0A0C]/95 pointer-events-none" />
        <div className="absolute inset-0 ring-1 ring-inset ring-white/10 rounded-[16px] pointer-events-none" />

        <div className="relative z-10 p-[16px]">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[12px] font-semibold text-[#F5F1EA] drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)]">
              Pipeline Capability
            </span>
            <span className="text-[12px] font-bold text-[#39C98A] drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)]">
              8 / 8 Active
            </span>
          </div>

          {/* Progress Bar (100%) */}
          <div className="h-[5px] rounded-full overflow-hidden bg-black/40 backdrop-blur-md mb-3 border border-white/10">
            <div
              className="h-full rounded-full transition-all duration-300 bg-gradient-to-r from-[#A87932] via-[#E8B968] to-[#39C98A] shadow-[0_0_10px_rgba(57,201,138,0.4)]"
              style={{ width: "100%" }}
            />
          </div>

          {/* Progress items */}
          <div className="space-y-1 text-[12px]">
            <div className="flex items-center justify-between py-0.5 border-b border-white/10">
              <div className="flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-[#39C98A]/25 border border-[#39C98A]/50 flex items-center justify-center text-[#39C98A]">
                  <Check size={9} strokeWidth={3} />
                </span>
                <span className="text-[#F5F1EA]">Phases 1–5</span>
              </div>
              <span className="text-[11px] text-[#B7AFBA]">Intel & Outreach</span>
            </div>

            <div className="flex items-center justify-between py-0.5 border-b border-white/10">
              <div className="flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-[#39C98A]/25 border border-[#39C98A]/50 flex items-center justify-center text-[#39C98A]">
                  <Check size={9} strokeWidth={3} />
                </span>
                <span className="text-[#F5F1EA]">Phase 6</span>
              </div>
              <span className="text-[11px] text-[#B7AFBA]">Website Builder</span>
            </div>

            <div className="flex items-center justify-between py-0.5 border-b border-white/10">
              <div className="flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-[#39C98A]/25 border border-[#39C98A]/50 flex items-center justify-center text-[#39C98A]">
                  <Check size={9} strokeWidth={3} />
                </span>
                <span className="text-[#F5F1EA] font-medium">Phase 7</span>
              </div>
              <span className="text-[10px] font-semibold px-1.5 py-0.2 rounded bg-[#39C98A]/15 border border-[#39C98A]/30 text-[#39C98A]">
                QA Evaluator
              </span>
            </div>

            <div className="flex items-center justify-between py-0.5">
              <div className="flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-[#39C98A]/25 border border-[#39C98A]/50 flex items-center justify-center text-[#39C98A]">
                  <Check size={9} strokeWidth={3} />
                </span>
                <span className="text-[#F5F1EA] font-medium">Phase 8</span>
              </div>
              <span className="text-[10px] font-semibold px-1.5 py-0.2 rounded bg-[#39C98A]/15 border border-[#39C98A]/30 text-[#39C98A]">
                Production Deploy
              </span>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
