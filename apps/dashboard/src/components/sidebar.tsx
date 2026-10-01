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
} from "lucide-react";

interface NavItem {
  href: string;
  label: string;
  icon: typeof Home;
  locked?: boolean;
}

const navItems: NavItem[] = [
  { href: "/dashboard", label: "Overview", icon: Home },
  { href: "/dashboard/leads", label: "Leads", icon: LayoutGrid },
  { href: "/dashboard/outreach", label: "Outreach", icon: Mail, locked: true },
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
        {/* 44px x 44px Icon Container with 12px radius */}
        <div className="w-[44px] h-[44px] rounded-[12px] bg-gradient-to-br from-[#F5CC7A] via-[#E8B968] to-[#A87932] flex items-center justify-center flex-shrink-0 shadow-[0_0_16px_rgba(232,185,105,0.22)] border border-[#F5CC7A]/40">
          <Sparkles className="w-5 h-5 text-[#17130D]" />
        </div>
        <div>
          <h2 className="text-[18px] font-semibold text-[#F5F1EA] tracking-tight leading-tight">
            AI Agency
          </h2>
          <p className="text-[12px] text-[#77717C] font-normal leading-none mt-1">
            Owner Dashboard
          </p>
        </div>
      </div>

      {/* Spacing between logo and navigation: 28-32px */}
      <div className="h-[28px] flex-shrink-0" />

      {/* 10. Navigation Items */}
      <nav className="flex flex-col gap-[6px]">
        {navItems.map((item) => {
          const { href, label, icon: Icon, locked } = item;
          const active =
            href === "/dashboard"
              ? pathname === "/dashboard"
              : pathname.startsWith(href);

          if (locked) {
            return (
              <div
                key={href}
                className="h-[44px] px-[14px] rounded-[10px] flex items-center justify-between text-[14px] text-[#77717C] opacity-75 cursor-not-allowed select-none"
                title="Phase 3: Outreach (Upcoming — locked)"
              >
                <div className="flex items-center gap-[10px]">
                  <Icon size={18} className="text-[#77717C]" />
                  <span>{label}</span>
                </div>
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#171519] border border-[#242126] text-[10px] font-mono text-[#77717C]">
                  <span>Phase 3</span>
                  <Lock size={10} />
                </div>
              </div>
            );
          }

          return (
            <Link
              key={href}
              href={href}
              className={`h-[44px] px-[14px] rounded-[10px] flex items-center justify-between text-[14px] transition-all duration-180 relative ${
                active
                  ? "bg-[rgba(232,185,105,0.12)] text-[#F5F1EA] font-semibold"
                  : "text-[#B7AFBA] hover:text-[#F5F1EA] hover:bg-[#171519]"
              }`}
            >
              {/* 2px gold accent line for active item */}
              {active && (
                <span className="absolute left-0 top-[8px] bottom-[8px] w-[2px] bg-[#E8B968] rounded-r" />
              )}
              <div className="flex items-center gap-[10px]">
                <Icon
                  size={18}
                  className={active ? "text-[#E8B968]" : "text-[#B7AFBA]"}
                />
                <span>{label}</span>
              </div>
            </Link>
          );
        })}
      </nav>

      {/* Flexible Spacer */}
      <div className="flex-1 min-h-[24px]" />

      {/* 23. Phase Progress Sidebar Card with Grand Mountain Background */}
      <div className="relative rounded-[16px] overflow-hidden border border-[#302A30] shadow-2xl group select-none">
        {/* Full-bleed Mountain Background */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/sidebar-mountain.jpg"
          alt="Alpine Horizon"
          className="absolute inset-0 w-full h-full object-cover object-center group-hover:scale-105 transition-transform duration-700 ease-out pointer-events-none"
        />
        {/* Cinematic dark luxury gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-b from-[#111013]/60 via-[#111013]/75 to-[#0B0A0C]/92 pointer-events-none" />
        <div className="absolute inset-0 ring-1 ring-inset ring-white/10 rounded-[16px] pointer-events-none" />

        {/* Card Content Layer */}
        <div className="relative z-10 p-[18px]">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[13px] font-semibold text-[#F5F1EA] drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)]">
              Phase Progress
            </span>
            <span className="text-[12px] font-bold text-[#E8B968] drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)]">
              2 / 8
            </span>
          </div>

          {/* 6px Gold Progress Bar */}
          <div className="h-[6px] rounded-full overflow-hidden bg-black/40 backdrop-blur-md mb-4 border border-white/10">
            <div
              className="h-full rounded-full transition-all duration-300 bg-gradient-to-r from-[#A87932] via-[#E8B968] to-[#F5CC7A] shadow-[0_0_10px_rgba(232,185,105,0.4)]"
              style={{ width: "25%" }}
            />
          </div>

          {/* Checklist: min 40px height per item */}
          <div className="space-y-1 text-[13px]">
            <div className="min-h-[40px] flex items-center justify-between py-1 border-b border-white/10">
              <div className="flex items-center gap-2.5">
                <span className="w-5 h-5 rounded-full bg-[#39C98A]/25 border border-[#39C98A]/50 flex items-center justify-center text-[#39C98A] shadow-sm">
                  <Check size={11} strokeWidth={3} />
                </span>
                <span className="text-[#F5F1EA] font-medium drop-shadow-sm">Phase 1</span>
              </div>
              <span className="text-[12px] text-[#B7AFBA]">Foundation</span>
            </div>

            <div className="min-h-[40px] flex items-center justify-between py-1 border-b border-white/10">
              <div className="flex items-center gap-2.5">
                <span className="w-5 h-5 rounded-full bg-[#39C98A]/25 border border-[#39C98A]/50 flex items-center justify-center text-[#39C98A] shadow-sm">
                  <Check size={11} strokeWidth={3} />
                </span>
                <span className="text-[#F5F1EA] font-medium drop-shadow-sm">Phase 2</span>
              </div>
              <span className="text-[12px] text-[#B7AFBA]">Lead Research</span>
            </div>

            <div className="min-h-[40px] flex items-center justify-between py-1">
              <div className="flex items-center gap-2.5">
                <span className="w-5 h-5 rounded-full border border-white/20 bg-black/30 flex items-center justify-center text-[#77717C]">
                  <Circle size={8} />
                </span>
                <span className="text-[#B7AFBA]">Phase 3</span>
              </div>
              <span className="text-[11px] font-medium px-2 py-0.5 rounded bg-black/50 border border-white/10 text-[#77717C] backdrop-blur-md">
                Upcoming
              </span>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
