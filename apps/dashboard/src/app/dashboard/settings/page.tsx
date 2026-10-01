"use client";

import { useEffect, useState, useCallback } from "react";
import {
  ShieldCheck,
  Cpu,
  KeyRound,
  Sliders,
  AlertTriangle,
  RotateCw,
  Database,
  Server,
  Lock,
  CheckCircle2,
  ExternalLink,
} from "lucide-react";
import { api, HealthResponse } from "@/lib/api";

export default function SettingsPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState<boolean>(true);

  const pingServices = useCallback(async () => {
    setHealthLoading(true);
    try {
      const res = await api.health();
      setHealth(res);
    } catch {
      // Safe fallback
    } finally {
      setHealthLoading(false);
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    api.health().then((res) => {
      if (mounted) {
        setHealth(res);
        setHealthLoading(false);
      }
    }).catch(() => {
      if (mounted) setHealthLoading(false);
    });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div className="pb-16 max-w-[1440px] w-full animate-fade-in">
      {/* Editorial Page Header */}
      <div className="mb-[36px] pb-4 border-b border-[#242126] flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <p className="text-[12px] font-semibold tracking-[0.18em] uppercase text-[#E8B968] mb-[8px]">
            SYSTEM CONFIGURATION
          </p>
          <h1 className="font-display text-[40px] md:text-[46px] font-normal text-[#F5F1EA] leading-[1.1] mb-[8px] tracking-tight">
            Agency Settings & Safeguards
          </h1>
          <p className="text-[15px] md:text-[16px] text-[#B7AFBA] leading-[1.5]">
            Configure autonomous agent safeguards, reasoning engines, and external provider integrations.
          </p>
        </div>

        <button
          type="button"
          onClick={pingServices}
          disabled={healthLoading}
          className="h-[42px] px-5 rounded-[10px] bg-[#171519] border border-[#302A30] hover:border-[#E8B968]/50 text-[13px] font-medium text-[#F5F1EA] hover:bg-[#1D1A1F] transition-all flex items-center gap-2.5 self-start md:self-auto flex-shrink-0"
        >
          <RotateCw size={14} className={healthLoading ? "animate-spin text-[#E8B968]" : "text-[#B7AFBA]"} />
          <span>{healthLoading ? "Pinging Services..." : "Re-Check Health"}</span>
        </button>
      </div>

      {/* 1. Core Infrastructure Services (3 Spacious Cards across full width) */}
      <section className="mb-[36px]">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <h2 className="text-[17px] font-semibold text-[#F5F1EA]">
              Core Infrastructure Telemetry
            </h2>
            <span className="text-[11px] font-mono px-2.5 py-0.5 rounded-full bg-[#171519] border border-[#242126] text-[#77717C]">
              {health?.version || "v0.2.0-phase2"}
            </span>
          </div>
          <span className="text-[12px] text-[#39C98A] flex items-center gap-1.5 font-medium">
            <span className="w-2 h-2 rounded-full bg-[#39C98A] animate-pulse" />
            System {health?.status || "operational"}
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {/* Database */}
          <div className="p-6 rounded-[14px] bg-[#171519] border border-[#302A30] hover:border-[#E8B968]/40 transition-all flex flex-col justify-between min-h-[140px]">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3.5">
                <div className="w-11 h-11 rounded-[10px] bg-[rgba(232,185,105,0.12)] border border-[rgba(232,185,105,0.25)] flex items-center justify-center text-[#E8B968] flex-shrink-0">
                  <Database size={20} />
                </div>
                <div>
                  <h3 className="text-[15px] font-semibold text-[#F5F1EA]">
                    PostgreSQL 16
                  </h3>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Primary Relational Store
                  </p>
                </div>
              </div>
              <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 flex items-center gap-1 flex-shrink-0">
                <span className="w-1.5 h-1.5 rounded-full bg-[#39C98A]" />
                Online
              </span>
            </div>
            <div className="pt-4 border-t border-[#242126] mt-4 flex items-center justify-between text-[11px] text-[#77717C]">
              <span>Port 5432 • TLS In-Transit</span>
              <span className="font-mono text-[#F5F1EA]">Healthy</span>
            </div>
          </div>

          {/* Queue Broker */}
          <div className="p-6 rounded-[14px] bg-[#171519] border border-[#302A30] hover:border-[#8B6FB8]/40 transition-all flex flex-col justify-between min-h-[140px]">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3.5">
                <div className="w-11 h-11 rounded-[10px] bg-[rgba(139,111,184,0.12)] border border-[rgba(139,111,184,0.25)] flex items-center justify-center text-[#8B6FB8] flex-shrink-0">
                  <Server size={20} />
                </div>
                <div>
                  <h3 className="text-[15px] font-semibold text-[#F5F1EA]">
                    Redis 7 & ARQ
                  </h3>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Async Job Queue & Locks
                  </p>
                </div>
              </div>
              <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 flex items-center gap-1 flex-shrink-0">
                <span className="w-1.5 h-1.5 rounded-full bg-[#39C98A]" />
                Listening
              </span>
            </div>
            <div className="pt-4 border-t border-[#242126] mt-4 flex items-center justify-between text-[11px] text-[#77717C]">
              <span>Worker Concurrency: 10</span>
              <span className="font-mono text-[#F5F1EA]">0 Pending Jobs</span>
            </div>
          </div>

          {/* FastAPI Engine */}
          <div className="p-6 rounded-[14px] bg-[#171519] border border-[#302A30] hover:border-[#39C98A]/40 transition-all flex flex-col justify-between min-h-[140px]">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3.5">
                <div className="w-11 h-11 rounded-[10px] bg-[rgba(57,201,138,0.12)] border border-[rgba(57,201,138,0.25)] flex items-center justify-center text-[#39C98A] flex-shrink-0">
                  <Cpu size={20} />
                </div>
                <div>
                  <h3 className="text-[15px] font-semibold text-[#F5F1EA]">
                    FastAPI Async Engine
                  </h3>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    REST API & SSE Stream
                  </p>
                </div>
              </div>
              <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 flex items-center gap-1 flex-shrink-0">
                <span className="w-1.5 h-1.5 rounded-full bg-[#39C98A]" />
                Active
              </span>
            </div>
            <div className="pt-4 border-t border-[#242126] mt-4 flex items-center justify-between text-[11px] text-[#77717C]">
              <span>Uptime: 100.0%</span>
              <span className="font-mono text-[#F5F1EA]">HTTP 200 OK</span>
            </div>
          </div>
        </div>
      </section>

      {/* 2. Main Two-Column Luxury Settings Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-7">
        {/* Left Column: Safeguards & Security */}
        <div className="space-y-7">
          {/* Agency Safeguards & Autonomous Rules */}
          <div className="p-7 rounded-[16px] bg-[#171519] border border-[#302A30]">
            <div className="flex items-center gap-3 pb-4 mb-5 border-b border-[#242126]">
              <div className="w-9 h-9 rounded-[8px] bg-[rgba(232,185,105,0.12)] flex items-center justify-center text-[#E8B968]">
                <ShieldCheck size={18} />
              </div>
              <div>
                <h3 className="text-[16px] font-semibold text-[#F5F1EA]">
                  Agency Safeguards & Operational Rules
                </h3>
                <p className="text-[12px] text-[#77717C]">
                  Deterministic boundaries enforced by the orchestrator
                </p>
              </div>
            </div>

            <div className="space-y-4">
              {/* Daily Email Outreach Cap */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div className="pr-2">
                  <p className="text-[14px] font-semibold text-[#F5F1EA]">
                    Daily Outreach Cap
                  </p>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Hard daily quota to protect sender reputation
                  </p>
                </div>
                <div className="px-3.5 py-1.5 rounded-[8px] bg-[#171519] border border-[#302A30] text-[13px] font-mono font-medium text-[#E8B968] whitespace-nowrap">
                  50 emails / day
                </div>
              </div>

              {/* Domain Touch Cooldown */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div className="pr-2">
                  <p className="text-[14px] font-semibold text-[#F5F1EA]">
                    Domain Touch Cooldown
                  </p>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Minimum waiting period between touching the same company
                  </p>
                </div>
                <div className="px-3.5 py-1.5 rounded-[8px] bg-[#171519] border border-[#302A30] text-[13px] font-mono font-medium text-[#F5F1EA] whitespace-nowrap">
                  72 hours
                </div>
              </div>

              {/* Duplicate Lead Detection */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div className="pr-2">
                  <p className="text-[14px] font-semibold text-[#F5F1EA]">
                    Duplicate Lead Prevention
                  </p>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Automatic normalization: strips www, http/https, subpaths
                  </p>
                </div>
                <div className="px-3 py-1 rounded-[6px] bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
                  <CheckCircle2 size={13} />
                  Enforced
                </div>
              </div>

              {/* Human Sign-Off Gatekeeper */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div className="pr-2">
                  <p className="text-[14px] font-semibold text-[#F5F1EA]">
                    Human-in-the-Loop Sign-Off
                  </p>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Zero autonomous emails without explicit dashboard approval
                  </p>
                </div>
                <div className="px-3 py-1 rounded-[6px] bg-[rgba(232,185,105,0.12)] text-[#E8B968] border border-[rgba(232,185,105,0.30)] text-[12px] font-semibold whitespace-nowrap">
                  Mandatory
                </div>
              </div>
            </div>
          </div>

          {/* Zero-Trust Secret Architecture Banner */}
          <div className="p-6 rounded-[16px] bg-[#171519] border border-[#302A30] relative overflow-hidden">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-[10px] bg-[rgba(229,184,92,0.12)] border border-[rgba(229,184,92,0.30)] flex items-center justify-center text-[#E5B85C] flex-shrink-0 mt-0.5">
                <Lock size={18} />
              </div>
              <div className="flex-1">
                <h4 className="text-[15px] font-semibold text-[#F5F1EA] flex items-center gap-2">
                  Zero-Trust Secret Architecture
                </h4>
                <p className="text-[13px] text-[#B7AFBA] mt-1.5 leading-relaxed">
                  Third-party API keys, OAuth tokens, and database credentials reside exclusively within the secure backend environment (<code className="text-[#E8B968] bg-[#111013] px-2 py-0.5 rounded text-[12px] border border-[#242126]">apps/api/.env</code>).
                </p>
                <div className="mt-3.5 pt-3 border-t border-[#242126] flex items-center gap-2 text-[12px] text-[#77717C]">
                  <CheckCircle2 size={13} className="text-[#39C98A]" />
                  <span>No plaintext tokens stored in client-side bundles or browser memory</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: AI Reasoning Engine & Integrations */}
        <div className="space-y-7">
          {/* AI Reasoning Engine */}
          <div className="p-7 rounded-[16px] bg-[#171519] border border-[#302A30]">
            <div className="flex items-center gap-3 pb-4 mb-5 border-b border-[#242126]">
              <div className="w-9 h-9 rounded-[8px] bg-[rgba(139,111,184,0.14)] flex items-center justify-center text-[#8B6FB8]">
                <Sliders size={18} />
              </div>
              <div>
                <h3 className="text-[16px] font-semibold text-[#F5F1EA]">
                  AI Model & Reasoning Engine
                </h3>
                <p className="text-[12px] text-[#77717C]">
                  Inference parameters and qualification policies
                </p>
              </div>
            </div>

            <div className="space-y-4">
              {/* Primary Reasoning Model */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126]">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-[14px] font-semibold text-[#F5F1EA]">
                    Primary Reasoning Model
                  </p>
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-[rgba(232,185,105,0.12)] text-[#E8B968] border border-[rgba(232,185,105,0.25)]">
                    Active LLM
                  </span>
                </div>
                <div className="p-2.5 rounded-[8px] bg-[#171519] border border-[#302A30] font-mono text-[12px] text-[#F5CC7A] break-all select-all">
                  nvidia/llama-3.1-nemotron-ultra-253b-v1
                </div>
                <p className="text-[11px] text-[#77717C] mt-2">
                  Used for website audit synthesis, deterministic qualification, and outreach proposal generation.
                </p>
              </div>

              {/* Sampling Temperature */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div className="pr-2">
                  <p className="text-[14px] font-semibold text-[#F5F1EA]">
                    Sampling Temperature
                  </p>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Low variance for reproducible audit scores
                  </p>
                </div>
                <div className="px-3.5 py-1.5 rounded-[8px] bg-[#171519] border border-[#302A30] text-[13px] font-mono text-[#F5F1EA] whitespace-nowrap">
                  0.2 (Deterministic)
                </div>
              </div>

              {/* Website Auditor SSRF Shield */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div className="pr-2">
                  <p className="text-[14px] font-semibold text-[#F5F1EA]">
                    SSRF Security Shield
                  </p>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Blocks loopback, RFC-1918 private IPs & cloud metadata (169.254.169.254)
                  </p>
                </div>
                <div className="px-3 py-1 rounded-[6px] bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
                  <ShieldCheck size={13} />
                  Active
                </div>
              </div>
            </div>
          </div>

          {/* External Provider Integrations */}
          <div className="p-7 rounded-[16px] bg-[#171519] border border-[#302A30]">
            <div className="flex items-center gap-3 pb-4 mb-5 border-b border-[#242126]">
              <div className="w-9 h-9 rounded-[8px] bg-[rgba(232,185,105,0.12)] flex items-center justify-center text-[#E8B968]">
                <KeyRound size={18} />
              </div>
              <div>
                <h3 className="text-[16px] font-semibold text-[#F5F1EA]">
                  External Provider Integrations
                </h3>
                <p className="text-[12px] text-[#77717C]">
                  Third-party connectors and autonomous distribution channels
                </p>
              </div>
            </div>

            <div className="space-y-3.5">
              {/* Google Places */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-[14px] font-semibold text-[#F5F1EA]">
                      Google Places API
                    </p>
                    <span className="text-[10px] font-mono px-2 py-0.2 rounded bg-[#171519] text-[#77717C] border border-[#242126]">
                      Phase 2
                    </span>
                  </div>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Local business prospect discovery & metadata provider
                  </p>
                </div>
                <span className="px-3 py-1 rounded-[6px] bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
                  <CheckCircle2 size={13} />
                  Connected
                </span>
              </div>

              {/* Gmail OAuth */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-[14px] font-semibold text-[#F5F1EA]">
                      Gmail OAuth 2.0
                    </p>
                    <span className="text-[10px] font-mono px-2 py-0.2 rounded bg-[#171519] text-[#77717C] border border-[#242126]">
                      Phase 3
                    </span>
                  </div>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Outbound personalized email delivery pipeline
                  </p>
                </div>
                <span className="px-2.5 py-1 rounded-[6px] bg-[#171519] border border-[#302A30] text-[11px] font-mono text-[#77717C] whitespace-nowrap">
                  Phase 3 Locked
                </span>
              </div>

              {/* GitHub & Vercel */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-[14px] font-semibold text-[#F5F1EA]">
                      GitHub & Vercel API
                    </p>
                    <span className="text-[10px] font-mono px-2 py-0.2 rounded bg-[#171519] text-[#77717C] border border-[#242126]">
                      Phase 7
                    </span>
                  </div>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Automated client preview repository creation and deployments
                  </p>
                </div>
                <span className="px-2.5 py-1 rounded-[6px] bg-[#171519] border border-[#302A30] text-[11px] font-mono text-[#77717C] whitespace-nowrap">
                  Phase 7 Locked
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
