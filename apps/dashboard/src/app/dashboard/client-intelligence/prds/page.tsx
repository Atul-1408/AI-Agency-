"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  FileText,
  Clock,
  CheckCircle,
  XCircle,
  RefreshCw,
  ArrowRight,
  ShieldCheck,
} from "lucide-react";
import { api, PRD, PRDStatus } from "@/lib/api";

export default function PRDListPage() {
  const [prds, setPrds] = useState<PRD[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  const fetchPRDs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.prd.list();
      setPrds(data || []);
    } catch {
      // Safe fallback
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPRDs();
  }, [fetchPRDs]);

  const getStatusBadge = (status: PRDStatus) => {
    switch (status) {
      case "approved":
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-[#1C3325] text-[#4ADE80] border border-[#235334]">
            <CheckCircle className="w-3 h-3" />
            <span>APPROVED</span>
          </span>
        );
      case "rejected":
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-[#36181B] text-[#F87171] border border-[#5A2429]">
            <XCircle className="w-3 h-3" />
            <span>REJECTED</span>
          </span>
        );
      case "superseded":
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-[#262329] text-[#9E95A2] border border-[#3D3842]">
            <span>SUPERSEDED</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-[#3A2D1B] text-[#FBBF24] border border-[#5C4724]">
            <Clock className="w-3 h-3" />
            <span>PENDING APPROVAL</span>
          </span>
        );
    }
  };

  return (
    <div className="pb-16 max-w-6xl mx-auto space-y-8 animate-fade-in">
      <div className="border-b border-[#242126] pb-4">
        <p className="text-[12px] font-semibold tracking-wider uppercase text-[#E8B968] mb-1">
          Gate 4 — Client Intelligence
        </p>
        <h1 className="font-display text-[32px] font-normal text-[#F5F1EA] tracking-tight">
          Product Requirement Documents (PRDs)
        </h1>
        <p className="text-[14px] text-[#B7AFBA] mt-1">
          Review, approve, or reject client website PRDs before project creation.
        </p>
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-24 space-y-3">
          <RefreshCw className="w-6 h-6 text-[#E8B968] animate-spin" />
          <p className="text-[13px] text-[#8F8795]">Loading PRD records...</p>
        </div>
      ) : prds.length === 0 ? (
        <div className="bg-[#1C1A1E] border border-[#2B2730] rounded-xl p-12 text-center space-y-3">
          <FileText className="w-10 h-10 text-[#5D5564] mx-auto" />
          <h3 className="text-[16px] font-medium text-[#F5F1EA]">No PRDs Generated Yet</h3>
          <p className="text-[13px] text-[#8F8795] max-w-sm mx-auto">
            PRDs are generated after client requirements are extracted from verified conversation threads.
          </p>
        </div>
      ) : (
        <div className="bg-[#18161A] border border-[#2B2730] rounded-xl overflow-hidden divide-y divide-[#242126]">
          {prds.map((p) => (
            <div
              key={p.id}
              className="p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 hover:bg-[#1E1B21] transition-colors"
            >
              <div className="space-y-1">
                <div className="flex items-center space-x-3">
                  <h4 className="text-[15px] font-medium text-[#F5F1EA]">{p.title}</h4>
                  <span className="text-[12px] text-[#E8B968] font-mono">v{p.version}</span>
                  {getStatusBadge(p.status)}
                </div>
                <p className="text-[12px] text-[#8F8795]">
                  Generated: {new Date(p.generated_at).toLocaleString()} • Owner: {p.owner_email}
                </p>
              </div>

              <div className="flex items-center space-x-3">
                <a
                  href={`/dashboard/client-intelligence/${p.conversation_id}/prd`}
                  className="px-4 py-2 bg-[#262329] hover:bg-[#322E36] text-[#F5F1EA] text-[12px] font-medium rounded-lg border border-[#3A3540] transition-colors flex items-center space-x-1.5"
                >
                  <span>Review PRD</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </a>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
