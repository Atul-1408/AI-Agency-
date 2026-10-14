"use client";

import { useEffect, useState } from "react";
import { Cpu, Activity, ShieldCheck, FolderKanban, Search, CheckSquare } from "lucide-react";
import { api } from "@/lib/api";

interface KpiData {
  phasesActive: string;
  totalRuns: number | string;
  totalProjects: number | string;
  totalLeads: number | string;
  pendingApprovals: number | string;
  systemStatus: string;
}

export function KpiCards() {
  const [data, setData] = useState<KpiData>({
    phasesActive: "7 of 8 Active",
    totalRuns: "0 Runs",
    totalProjects: "0 Projects",
    totalLeads: "0 Leads",
    pendingApprovals: "0 Pending",
    systemStatus: "System Operational",
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadLiveStats() {
      try {
        const [runsRes, healthRes, projectsRes, leadsRes, approvalsRes] =
          await Promise.allSettled([
            api.agents.listRuns({ page_size: 1 }),
            api.health(),
            api.projects.list(),
            api.leads.list({ page_size: 1 }),
            api.agents.listApprovals("pending"),
          ]);

        const totalRuns =
          runsRes.status === "fulfilled" && typeof runsRes.value?.total === "number"
            ? runsRes.value.total
            : 0;

        const totalProjects =
          projectsRes.status === "fulfilled" && typeof projectsRes.value?.total === "number"
            ? projectsRes.value.total
            : 0;

        const totalLeads =
          leadsRes.status === "fulfilled" && typeof leadsRes.value?.total === "number"
            ? leadsRes.value.total
            : 0;

        const pendingApprovals =
          approvalsRes.status === "fulfilled" && typeof approvalsRes.value?.total === "number"
            ? approvalsRes.value.total
            : 0;

        const isHealthy =
          healthRes.status === "fulfilled" && healthRes.value?.status === "ok";

        setData({
          phasesActive: "7 of 8 Active",
          totalRuns: `${totalRuns} Agent Runs`,
          totalProjects: `${totalProjects} Projects`,
          totalLeads: `${totalLeads} Leads`,
          pendingApprovals: `${pendingApprovals} Approvals Pending`,
          systemStatus: isHealthy ? "System Operational" : "System Degraded",
        });
      } catch {
        // Safe default
      } finally {
        setLoading(false);
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
      description: "Phases 1–7 fully operational, Phase 8 upcoming",
    },
    {
      id: "projects",
      icon: FolderKanban,
      iconColor: "#39C98A",
      iconBg: "rgba(57, 201, 138, 0.12)",
      value: data.totalProjects,
      description: "Build sessions, code generations & live previews",
    },
    {
      id: "leads",
      icon: Search,
      iconColor: "#8B6FB8",
      iconBg: "rgba(139, 111, 184, 0.12)",
      value: data.totalLeads,
      description: "Discovered prospects & audited businesses",
    },
    {
      id: "approvals",
      icon: CheckSquare,
      iconColor: "#E5B85C",
      iconBg: "rgba(229, 184, 92, 0.12)",
      value: data.pendingApprovals,
      description: "Human-in-the-loop review & QA gates",
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-[16px]">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <div
            key={card.id}
            className="min-h-[92px] p-[18px] rounded-[14px] bg-[#171519] border border-[#302A30] flex items-center gap-[16px] transition-transform duration-200 hover:-translate-y-[2px]"
          >
            <div
              className="w-[42px] h-[42px] rounded-[10px] flex items-center justify-center flex-shrink-0"
              style={{ backgroundColor: card.iconBg }}
            >
              <Icon size={19} style={{ color: card.iconColor }} />
            </div>

            <div className="flex flex-col text-left leading-tight min-w-0">
              <span className="text-[17px] font-semibold text-[#F5F1EA] tracking-tight truncate">
                {loading ? "..." : card.value}
              </span>
              <span className="text-[12px] text-[#77717C] mt-[4px] line-clamp-1">
                {card.description}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
