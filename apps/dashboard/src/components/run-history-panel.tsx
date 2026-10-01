"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Activity,
  RotateCw,
  Terminal,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  ChevronRight,
  Filter,
} from "lucide-react";
import { api, AgentRun } from "@/lib/api";

interface RunHistoryPanelProps {
  onTriggerFirstRun?: () => void;
}

export function RunHistoryPanel({ onTriggerFirstRun }: RunHistoryPanelProps) {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [selectedRun, setSelectedRun] = useState<AgentRun | null>(null);

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.agents.listRuns({
        status: statusFilter === "all" ? undefined : statusFilter,
        page_size: 25,
      });
      setRuns(res?.items || []);
    } catch {
      // Safe fallback
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    let mounted = true;
    api.agents
      .listRuns({
        status: statusFilter === "all" ? undefined : statusFilter,
        page_size: 25,
      })
      .then((res) => {
        if (mounted) {
          setRuns(res?.items || []);
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

  return (
    <div className="mt-[32px] p-[24px] rounded-[14px] bg-[#171519] border border-[#302A30] shadow-sm">
      {/* 22. Header with 48px height area */}
      <div className="min-h-[48px] flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#242126]">
        <div className="flex items-center gap-3">
          <div className="w-[36px] h-[36px] rounded-[10px] bg-[rgba(232,185,105,0.12)] flex items-center justify-center text-[#E8B968]">
            <Activity size={18} />
          </div>
          <div>
            <h3 className="text-[17px] font-semibold text-[#F5F1EA] tracking-tight">
              Run History
            </h3>
            <p className="text-[12px] text-[#77717C] mt-0.5">
              Live audit trail of autonomous agent jobs and system executions
            </p>
          </div>
        </div>

        {/* Filter and Refresh */}
        <div className="flex items-center gap-2.5">
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-[8px] bg-[#111013] border border-[#242126] text-[12px]">
            <Filter size={13} className="text-[#77717C]" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-transparent text-[#F5F1EA] text-[12px] focus:outline-none cursor-pointer"
            >
              <option value="all" className="bg-[#111013]">All Statuses</option>
              <option value="completed" className="bg-[#111013]">Completed</option>
              <option value="running" className="bg-[#111013]">Running</option>
              <option value="failed" className="bg-[#111013]">Failed</option>
            </select>
          </div>

          <button
            type="button"
            onClick={fetchRuns}
            className="p-2 rounded-[8px] bg-[#111013] border border-[#242126] text-[#B7AFBA] hover:text-[#F5F1EA] transition-colors"
            title="Refresh runs"
          >
            <RotateCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Content: Empty state or Table */}
      {runs.length === 0 ? (
        /* 22. Spacious Empty State with 32-40px vertical spacing */
        <div className="py-[40px] flex flex-col items-center justify-center text-center">
          <div className="w-[56px] h-[56px] rounded-[14px] bg-[#1D1A1F] border border-[#302A30] flex items-center justify-center text-[#77717C] mb-4">
            <Terminal size={24} />
          </div>

          <h4 className="text-[18px] font-semibold text-[#F5F1EA] tracking-tight">
            No runs yet
          </h4>

          <p className="text-[13px] text-[#77717C] mt-2 max-w-md leading-relaxed">
            Agent executions will appear here after a research or orchestration run.
          </p>

          <div className="mt-[24px]">
            <button
              type="button"
              onClick={onTriggerFirstRun}
              className="h-[44px] px-6 rounded-[10px] bg-[#E8B968] hover:bg-[#F5CC7A] text-[#17130D] text-[13px] font-semibold flex items-center gap-2 transition-all shadow-[0_2px_12px_rgba(232,185,105,0.2)]"
            >
              <Play size={13} fill="currentColor" />
              <span>Trigger Your First Run</span>
            </button>
          </div>
        </div>
      ) : (
        /* Populated Runs Table */
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead className="text-[11px] font-semibold text-[#77717C] uppercase tracking-wider border-b border-[#242126]">
              <tr>
                <th className="py-3 px-3">Agent</th>
                <th className="py-3 px-3">Status</th>
                <th className="py-3 px-3">Job ID</th>
                <th className="py-3 px-3">Tokens</th>
                <th className="py-3 px-3">Time</th>
                <th className="py-3 px-3 text-right">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#242126]/60">
              {runs.map((run) => (
                <tr
                  key={run.id}
                  onClick={() => setSelectedRun(run)}
                  className="hover:bg-[#1D1A1F]/50 transition-colors cursor-pointer"
                >
                  <td className="py-3.5 px-3">
                    <span className="font-semibold text-[#F5F1EA]">
                      {run.agent_name}
                    </span>
                  </td>
                  <td className="py-3.5 px-3">
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${
                        run.status === "completed"
                          ? "bg-[#39C98A]/10 text-[#39C98A] border-[#39C98A]/25"
                          : run.status === "running"
                          ? "bg-[#E8B968]/10 text-[#E8B968] border-[#E8B968]/25"
                          : "bg-[#E06B6B]/10 text-[#E06B6B] border-[#E06B6B]/25"
                      }`}
                    >
                      {run.status === "completed" ? (
                        <CheckCircle2 size={11} />
                      ) : run.status === "running" ? (
                        <Clock size={11} className="animate-spin" />
                      ) : (
                        <XCircle size={11} />
                      )}
                      <span>{run.status}</span>
                    </span>
                  </td>
                  <td className="py-3.5 px-3 font-mono text-[11px] text-[#77717C]">
                    {run.job_id || run.id}
                  </td>
                  <td className="py-3.5 px-3 font-mono text-[12px] text-[#B7AFBA]">
                    {run.tokens_used.toLocaleString()}
                  </td>
                  <td className="py-3.5 px-3 text-[12px] text-[#77717C]">
                    {new Date(run.created_at).toLocaleString([], {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td className="py-3.5 px-3 text-right">
                    <span className="text-[12px] text-[#E8B968] hover:underline inline-flex items-center gap-1">
                      Inspect <ChevronRight size={12} />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Selected Run Drawer / Modal */}
      {selectedRun && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-xs p-4">
          <div className="w-full max-w-lg rounded-[14px] bg-[#171519] border border-[#302A30] p-6 space-y-4 shadow-2xl animate-fade-in">
            <div className="flex items-center justify-between pb-3 border-b border-[#242126]">
              <div>
                <h4 className="text-[16px] font-semibold text-[#F5F1EA]">
                  Run Inspection: {selectedRun.agent_name}
                </h4>
                <p className="text-[11px] font-mono text-[#77717C] mt-0.5">
                  ID: {selectedRun.id}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedRun(null)}
                className="text-[#77717C] hover:text-[#F5F1EA]"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-[12px]">
              <div>
                <span className="text-[#77717C] font-semibold block mb-1">
                  Input Payload:
                </span>
                <pre className="p-3 rounded-[8px] bg-[#111013] border border-[#242126] font-mono text-[11px] text-[#B7AFBA] overflow-x-auto max-h-40">
                  {JSON.stringify(selectedRun.input_data, null, 2)}
                </pre>
              </div>

              <div>
                <span className="text-[#77717C] font-semibold block mb-1">
                  Output Data:
                </span>
                <pre className="p-3 rounded-[8px] bg-[#111013] border border-[#242126] font-mono text-[11px] text-[#39C98A] overflow-x-auto max-h-48">
                  {JSON.stringify(selectedRun.output_data, null, 2)}
                </pre>
              </div>
            </div>

            <div className="pt-2 flex justify-end">
              <button
                type="button"
                onClick={() => setSelectedRun(null)}
                className="px-4 py-2 rounded-[8px] bg-[#242126] text-[#F5F1EA] text-[12px] font-semibold hover:bg-[#302A30]"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
