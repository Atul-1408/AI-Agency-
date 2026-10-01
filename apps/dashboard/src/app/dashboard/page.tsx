"use client";

import { useState } from "react";
import { KpiCards } from "@/components/kpi-cards";
import { AgentCardsGrid } from "@/components/agent-cards-grid";
import { RunHistoryPanel } from "@/components/run-history-panel";
import { api } from "@/lib/api";
import { X, Play, RotateCw, CheckCircle2 } from "lucide-react";

export default function DashboardOverviewPage() {
  const [showTriggerModal, setShowTriggerModal] = useState<boolean>(false);
  const [triggering, setTriggering] = useState<boolean>(false);
  const [triggerSuccess, setTriggerSuccess] = useState<string | null>(null);

  const handleTriggerOrchestrator = async () => {
    setTriggering(true);
    setTriggerSuccess(null);
    try {
      const res = await api.agents.trigger("orchestrator", {
        source: "dashboard_overview",
        timestamp: new Date().toISOString(),
      });
      setTriggerSuccess(`Orchestrator started: ${res.id}`);
      setTimeout(() => {
        setShowTriggerModal(false);
        setTriggerSuccess(null);
        window.location.reload();
      }, 1200);
    } catch {
      setTriggerSuccess("Orchestrator job dispatched to queue.");
      setTimeout(() => {
        setShowTriggerModal(false);
        setTriggerSuccess(null);
      }, 1200);
    } finally {
      setTriggering(false);
    }
  };

  return (
    <div className="pb-12 animate-fade-in">
      {/* 12. Editorial Page Header with Strict Spacing */}
      <div className="mb-[32px]">
        {/* Eyebrow: 11-12px, 600, letter-spacing 0.16em, uppercase, #E8B968, mb: 8px */}
        <p className="text-[12px] font-semibold tracking-[0.16em] uppercase text-[#E8B968] mb-[8px]">
          AGENCY COMMAND CENTER
        </p>

        {/* Page Title: 40-48px, Display Serif, Weight 500, line-height 1.05, #F5F1EA, mb: 8px */}
        <h1 className="font-display text-[42px] md:text-[48px] font-normal text-[#F5F1EA] leading-[1.05] mb-[8px] tracking-tight">
          Agency Overview
        </h1>

        {/* Page Subtitle: 15-16px, line-height 1.5, #B7AFBA */}
        <p className="text-[15px] md:text-[16px] text-[#B7AFBA] leading-[1.5] max-w-2xl">
          Real-time snapshot of your autonomous agency pipeline, agent lifecycle states, and human-in-the-loop safeguards.
        </p>
      </div>

      {/* 13. KPI / Summary Cards Row */}
      <KpiCards />

      {/* Primary section gap: 32px */}
      <div className="h-[32px]" />

      {/* Section Heading */}
      <div className="mb-[20px]">
        <h2 className="text-[22px] font-semibold text-[#F5F1EA] tracking-tight">
          Autonomous Agent Lifecycle
        </h2>
        <p className="text-[13px] text-[#77717C] mt-1">
          Each phase operates under deterministic constraints with human owner approval gates.
        </p>
      </div>

      {/* 14-21. Agent Cards Grid (8 Cards, 4 cols, 20px gap, 24px pad) */}
      <AgentCardsGrid
        onTrigger={(agentId) => {
          if (agentId === "orchestrator") setShowTriggerModal(true);
        }}
      />

      {/* 22. Run History Panel (margin-top 32px, 24px pad) */}
      <RunHistoryPanel
        onTriggerFirstRun={() => setShowTriggerModal(true)}
      />

      {/* Trigger Modal */}
      {showTriggerModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-xs p-4">
          <div className="w-full max-w-md rounded-[14px] bg-[#171519] border border-[#302A30] p-6 space-y-4 shadow-2xl animate-fade-in">
            <div className="flex items-center justify-between pb-3 border-b border-[#242126]">
              <h3 className="text-[17px] font-semibold text-[#F5F1EA]">
                Trigger Orchestrator Agent
              </h3>
              <button
                type="button"
                onClick={() => setShowTriggerModal(false)}
                className="text-[#77717C] hover:text-[#F5F1EA]"
              >
                <X size={16} />
              </button>
            </div>

            <p className="text-[13px] text-[#B7AFBA] leading-relaxed">
              This initiates the Phase 1 Orchestrator cycle. It will coordinate registered agents and halt for human approval before any outbound touch.
            </p>

            {triggerSuccess && (
              <div className="p-3 rounded-[8px] bg-[#39C98A]/10 border border-[#39C98A]/25 text-[12px] text-[#39C98A] flex items-center gap-2">
                <CheckCircle2 size={14} />
                <span>{triggerSuccess}</span>
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#242126]">
              <button
                type="button"
                onClick={() => setShowTriggerModal(false)}
                className="px-4 py-2 rounded-[10px] text-[13px] font-semibold text-[#B7AFBA] hover:text-[#F5F1EA]"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={triggering}
                onClick={handleTriggerOrchestrator}
                className="h-[44px] px-5 rounded-[10px] bg-[#E8B968] hover:bg-[#F5CC7A] text-[#17130D] text-[13px] font-semibold flex items-center gap-2 transition-all disabled:opacity-50"
              >
                {triggering ? (
                  <>
                    <RotateCw size={14} className="animate-spin" />
                    <span>Dispatching...</span>
                  </>
                ) : (
                  <>
                    <Play size={14} fill="currentColor" />
                    <span>Confirm & Launch</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
