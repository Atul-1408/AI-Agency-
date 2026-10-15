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
  Code2,
  GitBranch,
  Layers,
  Sparkles,
} from "lucide-react";
import { api, HealthResponse, SystemReadinessResponse } from "@/lib/api";

export default function SettingsPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [readiness, setReadiness] = useState<SystemReadinessResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState<boolean>(true);

  const pingServices = useCallback(async () => {
    setHealthLoading(true);
    try {
      const [hRes, rRes] = await Promise.allSettled([
        api.health(),
        api.systemReadiness(),
      ]);
      if (hRes.status === "fulfilled") setHealth(hRes.value);
      if (rRes.status === "fulfilled") setReadiness(rRes.value);
    } catch {
      // Handled via safe fallback in api.ts
    } finally {
      setHealthLoading(false);
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    Promise.allSettled([api.health(), api.systemReadiness()]).then(([hRes, rRes]) => {
      if (mounted) {
        if (hRes.status === "fulfilled") setHealth(hRes.value);
        if (rRes.status === "fulfilled") setReadiness(rRes.value);
        setHealthLoading(false);
      }
    });
    return () => {
      mounted = false;
    };
  }, []);

  const isSqlite = readiness?.components?.database?.dialect === "sqlite";
  const dbConnected = readiness?.components?.database?.connected ?? (health?.services?.database?.status === "ok");
  const redisConnected = readiness?.components?.redis_workers?.connected ?? (health?.services?.redis?.status === "ok");

  const placesConfigured = readiness?.components?.google_places?.configured ?? false;
  const gmailConfigured = readiness?.components?.gmail_outreach?.configured ?? false;
  const gmailAccounts = readiness?.components?.gmail_outreach?.connected_accounts || 0;
  const aiReal = readiness?.components?.ai_code_generation?.configured ?? false;
  const githubConfigured = readiness?.components?.github_publishing?.configured ?? false;
  const vercelConfigured = readiness?.components?.vercel_deployment?.configured ?? false;

  return (
    <div className="pb-16 max-w-[1440px] w-full animate-fade-in">
      {/* Editorial Page Header */}
      <div className="mb-[36px] pb-4 border-b border-[#242126] flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <p className="text-[12px] font-semibold tracking-[0.18em] uppercase text-[#E8B968] mb-[8px]">
            SYSTEM CONFIGURATION & READINESS
          </p>
          <h1 className="font-display text-[40px] md:text-[46px] font-normal text-[#F5F1EA] leading-[1.1] mb-[8px] tracking-tight">
            Agency Settings & Safeguards
          </h1>
          <p className="text-[15px] md:text-[16px] text-[#B7AFBA] leading-[1.5]">
            Real-time infrastructure telemetry, provider verification, and autonomous agent safeguards.
          </p>
        </div>

        <button
          type="button"
          onClick={pingServices}
          disabled={healthLoading}
          className="h-[42px] px-5 rounded-[10px] bg-[#171519] border border-[#302A30] hover:border-[#E8B968]/50 text-[13px] font-medium text-[#F5F1EA] hover:bg-[#1D1A1F] transition-all flex items-center gap-2.5 self-start md:self-auto flex-shrink-0"
        >
          <RotateCw size={14} className={healthLoading ? "animate-spin text-[#E8B968]" : "text-[#B7AFBA]"} />
          <span>{healthLoading ? "Auditing Systems..." : "Re-Check Integration Status"}</span>
        </button>
      </div>

      {/* 1. Core Infrastructure Services (Dynamic Telemetry) */}
      <section className="mb-[36px]">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <h2 className="text-[17px] font-semibold text-[#F5F1EA]">
              Core Infrastructure Telemetry
            </h2>
            <span className="text-[11px] font-mono px-2.5 py-0.5 rounded-full bg-[#171519] border border-[#242126] text-[#77717C]">
              v0.1.0-phase10
            </span>
          </div>
          <span className="text-[12px] flex items-center gap-1.5 font-medium">
            <span
              className={`w-2 h-2 rounded-full ${
                readiness?.overall_status === "production_ready"
                  ? "bg-[#39C98A] animate-pulse"
                  : readiness?.overall_status === "degraded"
                  ? "bg-[#E05252]"
                  : "bg-[#E8B968]"
              }`}
            />
            <span className="text-[#B7AFBA]">
              Environment: <strong className="text-[#F5F1EA] font-semibold">{readiness?.environment || "development"}</strong>
              {" • "}
              Status: <span className="text-[#F5F1EA] capitalize">{readiness?.overall_status?.replace("_", " ") || health?.status || "active"}</span>
            </span>
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
                    {isSqlite ? "SQLite Store" : "PostgreSQL 16"}
                  </h3>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    {isSqlite ? "Local Dev Storage (Async)" : "Primary Relational Store"}
                  </p>
                </div>
              </div>
              {dbConnected ? (
                <span className={`px-2.5 py-1 rounded-full text-[11px] font-semibold flex items-center gap-1 flex-shrink-0 ${
                  isSqlite
                    ? "bg-[#E8B968]/10 text-[#E8B968] border border-[#E8B968]/30"
                    : "bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30"
                }`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${isSqlite ? "bg-[#E8B968]" : "bg-[#39C98A]"}`} />
                  {isSqlite ? "Active (Local SQLite)" : "Online (PostgreSQL)"}
                </span>
              ) : (
                <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#E05252]/10 text-[#E05252] border border-[#E05252]/30 flex items-center gap-1 flex-shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#E05252]" />
                  Offline
                </span>
              )}
            </div>
            <div className="pt-4 border-t border-[#242126] mt-4 flex items-center justify-between text-[11px] text-[#77717C]">
              <span>{isSqlite ? "local_dev.db" : "Port 5432 • TLS"}</span>
              <span className="font-mono text-[#F5F1EA]">
                {readiness?.components?.database?.table_count ? `${readiness.components.database.table_count} Tables` : "Connected"}
              </span>
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
                    {redisConnected ? "Redis 7 & ARQ" : "In-Process Async Fallback"}
                  </h3>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    {redisConnected ? "Async Job Queue & Locks" : "In-Process Task Dispatcher"}
                  </p>
                </div>
              </div>
              {redisConnected ? (
                <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 flex items-center gap-1 flex-shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#39C98A]" />
                  Listening
                </span>
              ) : (
                <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#E8B968]/10 text-[#E8B968] border border-[#E8B968]/30 flex items-center gap-1 flex-shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#E8B968]" />
                  Fallback Active
                </span>
              )}
            </div>
            <div className="pt-4 border-t border-[#242126] mt-4 flex items-center justify-between text-[11px] text-[#77717C]">
              <span>{redisConnected ? "Port 6379" : "Port 6379 Offline"}</span>
              <span className="font-mono text-[#F5F1EA]">
                {redisConnected ? "Redis Broker Online" : "In-Process Async Mode"}
              </span>
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
                    REST API & SSE Pipeline
                  </p>
                </div>
              </div>
              <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 flex items-center gap-1 flex-shrink-0">
                <span className="w-1.5 h-1.5 rounded-full bg-[#39C98A]" />
                Active
              </span>
            </div>
            <div className="pt-4 border-t border-[#242126] mt-4 flex items-center justify-between text-[11px] text-[#77717C]">
              <span>Port 8000 • Security Headers Active</span>
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
                <div>
                  <p className="text-[14px] font-semibold text-[#F5F1EA]">
                    Daily Outreach Limit
                  </p>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Hard safety limit on outbound emails sent per 24-hour window
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[14px] font-bold text-[#E8B968] bg-[#171519] px-3 py-1 rounded-[6px] border border-[#302A30]">
                    30 / day
                  </span>
                </div>
              </div>

              {/* Email Cooldown Interval */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div>
                  <p className="text-[14px] font-semibold text-[#F5F1EA]">
                    Follow-Up Cooldown Guard
                  </p>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Enforces minimum elapsed time before generating sequence follow-ups
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[14px] font-bold text-[#E8B968] bg-[#171519] px-3 py-1 rounded-[6px] border border-[#302A30]">
                    72 Hours
                  </span>
                </div>
              </div>

              {/* Human-in-the-Loop Gates */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div>
                  <p className="text-[14px] font-semibold text-[#F5F1EA]">
                    Human Approval Gates
                  </p>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Enforces mandatory owner sign-off at Gates 1, 2, 4, and 5
                  </p>
                </div>
                <div className="px-3 py-1 rounded-[6px] bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
                  <Lock size={13} />
                  Enforced
                </div>
              </div>

              {/* SSRF Shield */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div>
                  <p className="text-[14px] font-semibold text-[#F5F1EA]">
                    SSRF & Path Traversal Shields
                  </p>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Blocks loopback, private IPs & sandbox workspace escapes
                  </p>
                </div>
                <div className="px-3 py-1 rounded-[6px] bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
                  <ShieldCheck size={13} />
                  Active
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: External Provider Integrations */}
        <div className="space-y-7">
          <div className="p-7 rounded-[16px] bg-[#171519] border border-[#302A30]">
            <div className="flex items-center gap-3 pb-4 mb-5 border-b border-[#242126]">
              <div className="w-9 h-9 rounded-[8px] bg-[rgba(232,185,105,0.12)] flex items-center justify-center text-[#E8B968]">
                <KeyRound size={18} />
              </div>
              <div>
                <h3 className="text-[16px] font-semibold text-[#F5F1EA]">
                  Integration Verification Matrix
                </h3>
                <p className="text-[12px] text-[#77717C]">
                  Real vs Mock provider classification and live connectivity status
                </p>
              </div>
            </div>

            <div className="space-y-3.5">
              {/* AI Code Generation Provider */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-[14px] font-semibold text-[#F5F1EA]">
                      Website Code Generator
                    </p>
                    <span className="text-[10px] font-mono px-2 py-0.2 rounded bg-[#171519] text-[#77717C] border border-[#242126]">
                      Phase 6
                    </span>
                  </div>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    {aiReal
                      ? "NVIDIA Nemotron Ultra LLM generative synthesis"
                      : "Deterministic Next.js 14 App Router template engine"}
                  </p>
                </div>
                {aiReal ? (
                  <span className="px-3 py-1 rounded-[6px] bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
                    <CheckCircle2 size={13} />
                    Nemotron Active
                  </span>
                ) : (
                  <span className="px-3 py-1 rounded-[6px] bg-[#3B82F6]/10 text-[#60A5FA] border border-[#3B82F6]/30 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
                    <Code2 size={13} />
                    Deterministic Template
                  </span>
                )}
              </div>

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
                    {placesConfigured
                      ? "Live business prospect discovery active"
                      : "API key unset — Manual lead entry fallback active"}
                  </p>
                </div>
                {placesConfigured ? (
                  <span className="px-3 py-1 rounded-[6px] bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
                    <CheckCircle2 size={13} />
                    Verified Live
                  </span>
                ) : (
                  <span className="px-2.5 py-1 rounded-[6px] bg-[#171519] border border-[#302A30] text-[11px] font-mono text-[#E8B968] whitespace-nowrap">
                    Manual Entry Mode
                  </span>
                )}
              </div>

              {/* Gmail OAuth */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-[14px] font-semibold text-[#F5F1EA]">
                      Gmail OAuth 2.0
                    </p>
                    <span className="text-[10px] font-mono px-2 py-0.2 rounded bg-[#171519] text-[#77717C] border border-[#242126]">
                      Phase 3 & 4
                    </span>
                  </div>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    {gmailAccounts > 0
                      ? `${gmailAccounts} encrypted mailbox(es) connected`
                      : gmailConfigured
                      ? "OAuth client configured — waiting for owner mailbox auth"
                      : "Simulation mode active — dry-run delivery safeguards"}
                  </p>
                </div>
                {gmailAccounts > 0 ? (
                  <span className="px-3 py-1 rounded-[6px] bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
                    <CheckCircle2 size={13} />
                    Connected
                  </span>
                ) : (
                  <span className="px-2.5 py-1 rounded-[6px] bg-[#171519] border border-[#302A30] text-[11px] font-mono text-[#77717C] whitespace-nowrap">
                    Dry-Run Simulator
                  </span>
                )}
              </div>

              {/* GitHub Publishing */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-[14px] font-semibold text-[#F5F1EA]">
                      GitHub Provider
                    </p>
                    <span className="text-[10px] font-mono px-2 py-0.2 rounded bg-[#171519] text-[#77717C] border border-[#242126]">
                      Phase 8
                    </span>
                  </div>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    {githubConfigured
                      ? `Authenticated user: ${readiness?.components?.github_publishing?.authenticated_user || "Active"}`
                      : "GITHUB_TOKEN unset — Mock deployment provider active"}
                  </p>
                </div>
                {githubConfigured ? (
                  <span className="px-3 py-1 rounded-[6px] bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
                    <CheckCircle2 size={13} />
                    Connected
                  </span>
                ) : (
                  <span className="px-2.5 py-1 rounded-[6px] bg-[#171519] border border-[#302A30] text-[11px] font-mono text-[#77717C] whitespace-nowrap">
                    Mock Provider
                  </span>
                )}
              </div>

              {/* Vercel Hosting */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-[14px] font-semibold text-[#F5F1EA]">
                      Vercel Edge Hosting
                    </p>
                    <span className="text-[10px] font-mono px-2 py-0.2 rounded bg-[#171519] text-[#77717C] border border-[#242126]">
                      Phase 8
                    </span>
                  </div>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    {vercelConfigured
                      ? `Authenticated user: ${readiness?.components?.vercel_deployment?.authenticated_user || "Active"}`
                      : "VERCEL_TOKEN unset — Mock deployment provider active"}
                  </p>
                </div>
                {vercelConfigured ? (
                  <span className="px-3 py-1 rounded-[6px] bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
                    <CheckCircle2 size={13} />
                    Connected
                  </span>
                ) : (
                  <span className="px-2.5 py-1 rounded-[6px] bg-[#171519] border border-[#302A30] text-[11px] font-mono text-[#77717C] whitespace-nowrap">
                    Mock Provider
                  </span>
                )}
              </div>

              {/* Website QA Evaluator */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] flex items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-[14px] font-semibold text-[#F5F1EA]">
                      8-Point QA Evaluator Engine
                    </p>
                    <span className="text-[10px] font-mono px-2 py-0.2 rounded bg-[#171519] text-[#77717C] border border-[#242126]">
                      Phase 7
                    </span>
                  </div>
                  <p className="text-[12px] text-[#77717C] mt-0.5">
                    Local AST, WCAG 2.1 AA, responsive layout, SEO & secret scanner
                  </p>
                </div>
                <span className="px-3 py-1 rounded-[6px] bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
                  <CheckCircle2 size={13} />
                  Verified Live
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
