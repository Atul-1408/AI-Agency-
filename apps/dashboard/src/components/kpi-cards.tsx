"use client";

import { useEffect, useState } from "react";
import { Cpu, Activity, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";

interface KpiData {
  phasesActive: string;
  totalRuns: number | string;
  systemStatus: string;
}

export function KpiCards() {
  const [data, setData] = useState<KpiData>({
    phasesActive: "2 of 8 Phases Active",
    totalRuns: "0 Total Agent Runs",
    systemStatus: "System Operational",
  });

  useEffect(() => {
    async function loadLiveStats() {
      try {
        const [runsRes, healthRes] = await Promise.allSettled([
          api.agents.listRuns({ page_size: 1 }),
          api.health(),
        ]);

        const totalRuns =
          runsRes.status === "fulfilled" && typeof runsRes.value?.total === "number"
            ? runsRes.value.total
            : 0;

        const isHealthy =
          healthRes.status === "fulfilled" && healthRes.value?.status === "ok";

        setData({
          phasesActive: "2 of 8 Phases Active",
          totalRuns: `${totalRuns} Total Agent Runs`,
          systemStatus: isHealthy ? "System Operational" : "System Degraded",
        });
      } catch {
        // Safe default
      }
    }
    loadLiveStats();
  }, []);

  const cards = [
    {
      id: "phases",
      icon: Cpu,
      iconColor: "#E8B968",
      iconBg: "rgba(232, 185, 105, 0.12)",
      value: data.phasesActive,
      description: "Phase 1 Foundation & Phase 2 Lead Research",
    },
    {
      id: "runs",
      icon: Activity,
      iconColor: "#8B6FB8",
      iconBg: "rgba(139, 111, 184, 0.12)",
      value: data.totalRuns,
      description: "Autonomous execution history & telemetry",
    },
    {
      id: "system",
      icon: ShieldCheck,
      iconColor: "#39C98A",
      iconBg: "rgba(57, 201, 138, 0.12)",
      value: data.systemStatus,
      description: "FastAPI engine & ARQ workers online",
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-[20px]">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <div
            key={card.id}
            className="min-h-[96px] p-[20px] rounded-[14px] bg-[#171519] border border-[#302A30] flex items-center gap-[18px] transition-transform duration-200 hover:-translate-y-[2px]"
          >
            {/* 44x44px Icon Container */}
            <div
              className="w-[44px] h-[44px] rounded-[10px] flex items-center justify-center flex-shrink-0"
              style={{ backgroundColor: card.iconBg }}
            >
              <Icon size={20} style={{ color: card.iconColor }} />
            </div>

            {/* Value & Supporting Description */}
            <div className="flex flex-col text-left leading-tight">
              <span className="text-[19px] font-semibold text-[#F5F1EA] tracking-tight">
                {card.value}
              </span>
              <span className="text-[13px] text-[#77717C] mt-[5px]">
                {card.description}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
