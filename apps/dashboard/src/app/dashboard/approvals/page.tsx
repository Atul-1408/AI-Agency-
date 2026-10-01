"use client";

import { useEffect, useState, useCallback } from "react";
import {
  ShieldCheck,
  CheckCircle2,
  Check,
  X,
  RotateCw,
} from "lucide-react";
import { api, ApprovalRequest } from "@/lib/api";

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("pending");
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchApprovals = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.agents.listApprovals(
        statusFilter === "all" ? undefined : statusFilter
      );
      setApprovals(res?.items || []);
    } catch {
      // Safe fallback
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    let mounted = true;
    api.agents
      .listApprovals(statusFilter === "all" ? undefined : statusFilter)
      .then((res) => {
        if (mounted) {
          setApprovals(res?.items || []);
          setLoading(false);
        }
      })
      .catch(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [statusFilter]);

  const handleDecision = async (id: string, decision: "approved" | "rejected") => {
    setActionLoading(id);
    try {
      await api.agents.decide(id, decision, "Reviewed by owner");
      await fetchApprovals();
    } catch {
      // fallback
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="pb-12 animate-fade-in">
      {/* 12. Editorial Page Header with Strict Spacing */}
      <div className="mb-[32px] pb-2 border-b border-[#242126]">
        <p className="text-[12px] font-semibold tracking-[0.16em] uppercase text-[#E8B968] mb-[8px]">
          HUMAN-IN-THE-LOOP SAFEGUARDS
        </p>

        <h1 className="font-display text-[42px] md:text-[48px] font-normal text-[#F5F1EA] leading-[1.05] mb-[8px] tracking-tight">
          Approval Queue
        </h1>

        <p className="text-[15px] md:text-[16px] text-[#B7AFBA] leading-[1.5] max-w-2xl">
          Every autonomous agent action that requires explicit owner sign-off appears here before execution.
        </p>
      </div>

      {/* Safety Policy Banner with 24px padding */}
      <div className="p-[24px] rounded-[14px] bg-[#171519] border border-[#302A30] flex flex-col md:flex-row md:items-center justify-between gap-4 mb-[32px]">
        <div className="flex items-start gap-3.5">
          <div className="w-[44px] h-[44px] rounded-[10px] bg-[rgba(232,185,105,0.12)] flex items-center justify-center text-[#E8B968] flex-shrink-0">
            <ShieldCheck size={22} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-[16px] font-semibold text-[#F5F1EA]">
                Autonomous Execution Safeguard Enforced
              </h3>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30">
                ACTIVE
              </span>
            </div>
            <p className="text-[13px] text-[#B7AFBA] mt-1 max-w-2xl leading-relaxed">
              Outbound emails, public repository generation, and live production website deployments strictly halt until explicit human approval is confirmed.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 border-t md:border-t-0 md:border-l border-[#242126] pt-3 md:pt-0 md:pl-6 flex-shrink-0 text-[12px]">
          <div>
            <span className="text-[#77717C] block">Daily Outbound Cap</span>
            <span className="font-semibold text-[#F5F1EA]">50 emails / day</span>
          </div>
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center justify-between gap-4 mb-[20px]">
        <div className="flex items-center gap-1.5 p-1.5 rounded-[12px] bg-[#171519] border border-[#302A30]">
          {[
            { id: "pending", label: "Pending Sign-Off" },
            { id: "approved", label: "Approved" },
            { id: "rejected", label: "Rejected" },
            { id: "all", label: "All Items" },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setStatusFilter(tab.id)}
              className={`h-[38px] px-4 rounded-[8px] text-[13px] font-medium transition-all whitespace-nowrap flex items-center justify-center ${
                statusFilter === tab.id
                  ? "bg-[rgba(232,185,105,0.15)] text-[#F5CC7A] font-semibold border border-[rgba(232,185,105,0.35)] shadow-sm"
                  : "text-[#B7AFBA] hover:text-[#F5F1EA] hover:bg-[#1D1A1F]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={fetchApprovals}
          className="p-2 rounded-[8px] bg-[#171519] border border-[#302A30] text-[#B7AFBA] hover:text-[#F5F1EA] transition-colors"
          title="Refresh Queue"
        >
          <RotateCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Approvals List or Empty State */}
      {approvals.length === 0 ? (
        /* Spacious Empty State */
        <div className="py-[64px] rounded-[14px] bg-[#171519] border border-[#302A30] flex flex-col items-center justify-center text-center p-8">
          <div className="w-[56px] h-[56px] rounded-[14px] bg-[#1D1A1F] border border-[#302A30] flex items-center justify-center text-[#39C98A] mb-4">
            <CheckCircle2 size={24} />
          </div>
          <h4 className="text-[19px] font-semibold text-[#F5F1EA] tracking-tight">
            Queue is Clear
          </h4>
          <p className="text-[14px] text-[#77717C] mt-2 max-w-md leading-relaxed">
            All agent workflows are currently running within safe boundaries. Pending actions will notify you here in real time.
          </p>
        </div>
      ) : (
        <div className="space-y-[16px]">
          {approvals.map((item) => (
            <div
              key={item.id}
              className="p-[24px] rounded-[14px] bg-[#171519] border border-[#302A30] flex flex-col md:flex-row md:items-center justify-between gap-4"
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-semibold uppercase px-2 py-0.5 rounded bg-[#1D1A1F] text-[#E8B968] border border-[#302A30]">
                    {item.action_type.replace(/_/g, " ")}
                  </span>
                  <span className="text-[12px] font-mono text-[#77717C]">{item.id}</span>
                </div>
                <h4 className="text-[16px] font-semibold text-[#F5F1EA] mt-2">
                  {String(item.payload?.company_name || item.payload?.lead_id || "Prospect Item")}
                </h4>
                {Boolean(item.payload?.recommended_angle) && (
                  <p className="text-[13px] text-[#B7AFBA] mt-1 italic">
                    &quot;{String(item.payload.recommended_angle)}&quot;
                  </p>
                )}
              </div>

              {item.status === "pending" ? (
                <div className="flex items-center gap-2.5 flex-shrink-0">
                  <button
                    type="button"
                    disabled={actionLoading === item.id}
                    onClick={() => handleDecision(item.id, "approved")}
                    className="h-[42px] px-5 rounded-[10px] bg-[#E8B968] hover:bg-[#F5CC7A] text-[#17130D] text-[13px] font-semibold flex items-center gap-2 transition-all disabled:opacity-50"
                  >
                    <Check size={14} strokeWidth={2.5} />
                    <span>Approve</span>
                  </button>
                  <button
                    type="button"
                    disabled={actionLoading === item.id}
                    onClick={() => handleDecision(item.id, "rejected")}
                    className="h-[42px] px-4 rounded-[10px] bg-[#1D1A1F] hover:bg-[#242126] border border-[#302A30] text-[#E06B6B] text-[13px] font-semibold flex items-center gap-1.5 transition-colors disabled:opacity-50"
                  >
                    <X size={14} />
                    <span>Reject</span>
                  </button>
                </div>
              ) : (
                <span
                  className={`text-[12px] font-semibold px-3 py-1 rounded-full uppercase border ${
                    item.status === "approved"
                      ? "bg-[#39C98A]/10 text-[#39C98A] border-[#39C98A]/30"
                      : "bg-[#E06B6B]/10 text-[#E06B6B] border-[#E06B6B]/30"
                  }`}
                >
                  {item.status}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
