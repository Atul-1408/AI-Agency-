"use client";

import { Search, Bell, ChevronDown } from "lucide-react";

export function Header() {
  return (
    <header className="h-[68px] flex items-center justify-between px-8 border-b border-[#242126] bg-[#0B0A0C]/90 backdrop-blur-md flex-shrink-0 select-none z-10">
      {/* 11. Search Bar */}
      <div className="relative w-[420px] max-w-full">
        <Search
          size={18}
          className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#77717C] pointer-events-none"
        />
        <input
          type="text"
          placeholder="Search agents, runs, or leads..."
          className="w-full h-[42px] pl-11 pr-14 rounded-[10px] text-[13px] border border-[#302A30] bg-[#171519]/75 text-[#F5F1EA] placeholder-[#77717C] focus:outline-none focus:border-[#E8B968]/50 transition-colors"
        />
        <span className="absolute right-3 top-1/2 -translate-y-1/2 px-1.5 py-0.5 rounded text-[10px] font-mono border border-[#302A30] bg-[#1D1A1F] text-[#77717C]">
          Ctrl K
        </span>
      </div>

      {/* Right Header Section */}
      <div className="flex items-center gap-6">
        {/* Notification Bell */}
        <button
          className="relative p-2 rounded-[8px] text-[#B7AFBA] hover:text-[#F5F1EA] hover:bg-[#171519] transition-colors"
          title="Notifications"
          type="button"
        >
          <Bell size={19} />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-[#E06B6B] ring-2 ring-[#0B0A0C]" />
        </button>

        {/* Divider */}
        <div className="w-[1px] h-6 bg-[#242126]" />

        {/* Owner Profile Block */}
        <div className="flex items-center gap-3 cursor-pointer group">
          <div className="w-[36px] h-[36px] rounded-full flex items-center justify-center text-[13px] font-bold text-white shadow-md ring-1 ring-[#8B6FB8]/50 bg-gradient-to-br from-[#8B6FB8] to-[#5B3E84] flex-shrink-0">
            A
          </div>
          <div className="flex flex-col text-left leading-tight">
            <span className="text-[14px] font-semibold text-[#F5F1EA] group-hover:text-[#E8B968] transition-colors">
              Atul
            </span>
            <span className="text-[12px] text-[#77717C]">Agency Owner</span>
          </div>
          <ChevronDown
            size={15}
            className="text-[#77717C] group-hover:text-[#F5F1EA] transition-colors ml-1"
          />
        </div>
      </div>
    </header>
  );
}
