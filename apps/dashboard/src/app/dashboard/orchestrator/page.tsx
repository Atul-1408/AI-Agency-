"use client";

import { useEffect, useState, useCallback } from "react";
import {
  GitBranch,
  Play,
  RotateCw,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock,
  ShieldAlert,
  ShieldCheck,
  Eye,
  Server,
  Database,
  Mail,
  Code2,
  Zap,
  ChevronRight,
  Plus,
  RefreshCw,
  AlertTriangle,
  Lock,
  ArrowRight,
  ExternalLink,
} from "lucide-react";
import {
  api,
  AgentWorkflow,
  WorkflowStage,
  WorkflowExecutionMode,
  WorkflowStatus,
  ProviderConnectivityResponse,
  WorkflowStepRecord,
} from "@/lib/api";

const STAGES_CANONICAL: { id: WorkflowStage; label: string; agent: string; isGate?: boolean }[] = [
  { id: "lead_discovery", label: "Lead Discovery", agent: "Lead Research" },
  { id: "research", label: "Technical Audit", agent: "Lead Research" },
  { id: "qualification", label: "Opportunity Scoring", agent: "Lead Research" },
  { id: "gate_1_lead_approval", label: "Gate 1: Lead Review", agent: "Owner Approval", isGate: true },
  { id: "outreach_draft", label: "Outreach Drafting", agent: "Outreach Agent" },
  { id: "gate_2_outreach_approval", label: "Gate 2: Draft Review", agent: "Owner Approval", isGate: true },
  { id: "safety_checks", label: "Safety & Suppression", agent: "Outreach Agent" },
  { id: "gmail_dispatch", label: "Gmail Dispatch", agent: "Outreach Agent" },
  { id: "reply_detection", label: "Inbound Thread Detect", agent: "Follow-up Agent" },
  { id: "client_requirements", label: "Extract Requirements", agent: "Client Intelligence" },
  { id: "requirement_review", label: "Review & Traceability", agent: "Client Intelligence" },
  { id: "prd_generation", label: "PRD Formulation", agent: "Client Intelligence" },
  { id: "gate_4_prd_approval", label: "Gate 4: PRD Approval", agent: "Owner Approval", isGate: true },
  { id: "project_creation", label: "Project Activation", agent: "Website Builder" },
  { id: "website_specification", label: "Website Specification", agent: "Website Builder" },
  { id: "design_blueprint", label: "Design Blueprint", agent: "Website Builder" },
  { id: "code_generation", label: "Next.js Code Generation", agent: "Website Builder" },
  { id: "preview_and_editing", label: "Preview Sandbox", agent: "Website Builder" },
  { id: "website_qa", label: "8-Point QA Evaluator", agent: "QA Agent" },
  { id: "repair_and_recheck", label: "QA Repair & Recheck", agent: "QA Agent" },
  { id: "gate_5_deployment_approval", label: "Gate 5: Deploy Approval", agent: "Owner Approval", isGate: true },
  { id: "github_publishing", label: "GitHub Sync", agent: "Deployment Agent" },
  { id: "vercel_deployment", label: "Vercel Edge Deploy", agent: "Deployment Agent" },
  { id: "deployment_verification", label: "Endpoint & SSL Check", agent: "Deployment Agent" },
];

export default function OrchestratorPage() {
  const [workflows, setWorkflows] = useState<AgentWorkflow[]>([]);
  const [selectedWf, setSelectedWf] = useState<AgentWorkflow | null>(null);
  const [connectivity, setConnectivity] = useState<ProviderConnectivityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showApprovalModal, setShowApprovalModal] = useState(false);
  const [approvalNotes, setApprovalNotes] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [bannerMessage, setBannerMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

  // New Workflow Form State
  const [formTitle, setFormTitle] = useState("");
  const [formCompany, setFormCompany] = useState("");
  const [formDomain, setFormDomain] = useState("");
  const [formMode, setFormMode] = useState<WorkflowExecutionMode>("supervised");
  const [formDryRun, setFormDryRun] = useState(false);

  const fetchConnectivity = useCallback(async () => {
    try {
      const data = await api.workflow.connectivity();
      setConnectivity(data);
    } catch (e) {
      console.error("Failed to load connectivity:", e);
    }
  }, []);

  const loadWorkflows = useCallback(async () => {
    try {
      setLoading(true);
      const res = await api.workflow.list({
        status: statusFilter === "all" ? undefined : statusFilter,
        page_size: 50,
      });
      setWorkflows(res.items);
      if (res.items.length > 0) {
        setSelectedWf((prev) => {
          if (!prev) return res.items[0];
          const found = res.items.find((w) => w.id === prev.id);
          return found ?? res.items[0];
        });
      } else {
        setSelectedWf(null);
      }
    } catch (err: unknown) {
      console.error("Failed to load workflows:", err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    loadWorkflows();
    fetchConnectivity();
  }, [loadWorkflows, fetchConnectivity]);

  const handleCreateWorkflow = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formTitle.trim()) return;
    try {
      setActionLoading(true);
      const created = await api.workflow.create({
        title: formTitle.trim(),
        mode: formMode,
        is_dry_run: formDryRun,
        initial_data: {
          company_name: formCompany.trim() || "Apex Design Studios",
          domain: formDomain.trim() || "apexdesign.example.com",
        },
      });
      setBannerMessage({ text: `Workflow "${created.title}" successfully created.`, type: "success" });
      setShowCreateModal(false);
      setFormTitle("");
      setFormCompany("");
      setFormDomain("");
      await loadWorkflows();
      setSelectedWf(created);
    } catch (err: unknown) {
      const msg = err && typeof err === "object" && "detail" in err ? String(err.detail) : "Creation failed";
      setBannerMessage({ text: msg, type: "error" });
    } finally {
      setActionLoading(false);
    }
  };

  const handleAdvance = async () => {
    if (!selectedWf) return;
    try {
      setActionLoading(true);
      const updated = await api.workflow.advance(selectedWf.id);
      setSelectedWf(updated);
      setBannerMessage({ text: `Stage advanced to ${updated.current_stage.replace(/_/g, " ")}.`, type: "success" });
      await loadWorkflows();
    } catch (err: unknown) {
      const msg = err && typeof err === "object" && "detail" in err ? String(err.detail) : "Advance failed";
      setBannerMessage({ text: msg, type: "error" });
    } finally {
      setActionLoading(false);
    }
  };

  const handleApproval = async (decision: "approved" | "rejected") => {
    if (!selectedWf) return;
    try {
      setActionLoading(true);
      const updated = await api.workflow.approve(selectedWf.id, {
        decision,
        notes: approvalNotes.trim() || undefined,
      });
      setSelectedWf(updated);
      setShowApprovalModal(false);
      setApprovalNotes("");
      setBannerMessage({
        text: `Gate ${decision === "approved" ? "approved" : "rejected"} successfully.`,
        type: "success",
      });
      await loadWorkflows();
    } catch (err: unknown) {
      const msg = err && typeof err === "object" && "detail" in err ? String(err.detail) : "Approval action failed";
      setBannerMessage({ text: msg, type: "error" });
    } finally {
      setActionLoading(false);
    }
  };

  const handleRetry = async () => {
    if (!selectedWf) return;
    try {
      setActionLoading(true);
      const updated = await api.workflow.retry(selectedWf.id);
      setSelectedWf(updated);
      setBannerMessage({ text: `Stage ${updated.current_stage} restarted.`, type: "success" });
      await loadWorkflows();
    } catch (err: unknown) {
      const msg = err && typeof err === "object" && "detail" in err ? String(err.detail) : "Retry failed";
      setBannerMessage({ text: msg, type: "error" });
    } finally {
      setActionLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!selectedWf) return;
    try {
      setActionLoading(true);
      const updated = await api.workflow.cancel(selectedWf.id, cancelReason.trim() || undefined);
      setSelectedWf(updated);
      setShowCancelModal(false);
      setCancelReason("");
      setBannerMessage({ text: "Workflow cancelled.", type: "success" });
      await loadWorkflows();
    } catch (err: unknown) {
      const msg = err && typeof err === "object" && "detail" in err ? String(err.detail) : "Cancellation failed";
      setBannerMessage({ text: msg, type: "error" });
    } finally {
      setActionLoading(false);
    }
  };

  const getStatusBadge = (status: WorkflowStatus) => {
    switch (status) {
      case "running":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30">
            <span className="w-1.5 h-1.5 rounded-full bg-[#39C98A] animate-pulse" /> Running
          </span>
        );
      case "paused_for_approval":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium bg-[#E8B968]/15 text-[#F5CC7A] border border-[#E8B968]/40 animate-pulse">
            <Lock className="w-3 h-3" /> Gate Approval Required
          </span>
        );
      case "completed":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium bg-[#39C98A]/15 text-[#39C98A] border border-[#39C98A]/30">
            <CheckCircle2 className="w-3 h-3" /> Completed
          </span>
        );
      case "failed":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium bg-[#EB5757]/15 text-[#EB5757] border border-[#EB5757]/30">
            <XCircle className="w-3 h-3" /> Failed
          </span>
        );
      case "cancelled":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium bg-[#77717C]/20 text-[#A098A8] border border-[#77717C]/30">
            Cancelled
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium bg-[#1B191E] text-[#B7AFBA] border border-[#2B2730]">
            Created
          </span>
        );
    }
  };

  const currentStageIndex = selectedWf
    ? STAGES_CANONICAL.findIndex((s) => s.id === selectedWf.current_stage)
    : -1;

  return (
    <div className="space-y-6 pb-12 max-w-[1600px] mx-auto">
      {/* Top Banner Alert */}
      {bannerMessage && (
        <div
          className={`flex items-center justify-between px-4 py-3 rounded-xl border text-[13px] ${
            bannerMessage.type === "success"
              ? "bg-[#39C98A]/10 border-[#39C98A]/30 text-[#39C98A]"
              : "bg-[#EB5757]/10 border-[#EB5757]/30 text-[#EB5757]"
          }`}
        >
          <div className="flex items-center gap-2">
            {bannerMessage.type === "success" ? <CheckCircle2 className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
            <span>{bannerMessage.text}</span>
          </div>
          <button onClick={() => setBannerMessage(null)} className="text-xs hover:underline opacity-80">
            Dismiss
          </button>
        </div>
      )}

      {/* Header Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-[#242126] pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-gradient-to-br from-[#E8B968]/20 to-[#A87932]/10 border border-[#E8B968]/30 text-[#F5CC7A]">
              <GitBranch className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-[#F5F1EA] tracking-tight">
                Central Agent Orchestrator
              </h1>
              <p className="text-xs text-[#8A8490] mt-0.5">
                Phase 9 Complete 24-Stage Multi-Agent Orchestration & Deterministic Governance
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              loadWorkflows();
              fetchConnectivity();
            }}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#17151A] border border-[#2B2730] text-[#B7AFBA] hover:text-[#F5F1EA] hover:border-[#3E3845] text-xs font-medium transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>

          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-[#E8B968] to-[#C99846] text-[#0B0A0C] font-semibold text-xs shadow-[0_0_15px_rgba(232,185,105,0.25)] hover:brightness-110 transition"
          >
            <Plus className="w-4 h-4" />
            New Multi-Agent Workflow
          </button>
        </div>
      </div>

      {/* Provider Connectivity Bar */}
      {connectivity && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <div className="p-3 rounded-xl bg-[#131215] border border-[#222026] flex items-center gap-3">
            <Database className={`w-4 h-4 ${connectivity.database.connected ? "text-[#39C98A]" : "text-[#EB5757]"}`} />
            <div className="min-w-0">
              <div className="text-[11px] font-medium text-[#77717C]">Database</div>
              <div className="text-[12px] font-semibold text-[#F5F1EA] truncate">
                {connectivity.database.connected ? (connectivity.database.dialect === "sqlite" ? "SQLite (Local)" : "PostgreSQL") : "Disconnected"}
              </div>
            </div>
          </div>

          <div className="p-3 rounded-xl bg-[#131215] border border-[#222026] flex items-center gap-3">
            <Server className={`w-4 h-4 ${connectivity.redis_queue.connected ? "text-[#39C98A]" : "text-[#E8B968]"}`} />
            <div className="min-w-0">
              <div className="text-[11px] font-medium text-[#77717C]">Redis Worker</div>
              <div className="text-[12px] font-semibold text-[#F5F1EA] truncate">
                {connectivity.redis_queue.connected ? "Active" : "In-Process Async"}
              </div>
            </div>
          </div>

          <div className="p-3 rounded-xl bg-[#131215] border border-[#222026] flex items-center gap-3">
            <Zap className={`w-4 h-4 ${connectivity.ai_provider.configured ? "text-[#39C98A]" : "text-[#60A5FA]"}`} />
            <div className="min-w-0">
              <div className="text-[11px] font-medium text-[#77717C]">AI Generator</div>
              <div className="text-[12px] font-semibold text-[#F5F1EA] truncate">
                {connectivity.ai_provider.configured ? connectivity.ai_provider.provider : "Deterministic"}
              </div>
            </div>
          </div>

          <div className="p-3 rounded-xl bg-[#131215] border border-[#222026] flex items-center gap-3">
            <Mail className={`w-4 h-4 ${connectivity.gmail.configured ? "text-[#39C98A]" : "text-[#77717C]"}`} />
            <div className="min-w-0">
              <div className="text-[11px] font-medium text-[#77717C]">Gmail OAuth</div>
              <div className="text-[12px] font-semibold text-[#F5F1EA] truncate">
                {connectivity.gmail.configured ? "Configured" : "Dry-Run Sim"}
              </div>
            </div>
          </div>

          <div className="p-3 rounded-xl bg-[#131215] border border-[#222026] flex items-center gap-3">
            <Code2 className={`w-4 h-4 ${connectivity.github.configured ? "text-[#39C98A]" : "text-[#77717C]"}`} />
            <div className="min-w-0">
              <div className="text-[11px] font-medium text-[#77717C]">GitHub Sync</div>
              <div className="text-[12px] font-semibold text-[#F5F1EA] truncate">
                {connectivity.github.configured ? "Ready" : "Mock Fallback"}
              </div>
            </div>
          </div>

          <div className="p-3 rounded-xl bg-[#131215] border border-[#222026] flex items-center gap-3">
            <Server className={`w-4 h-4 ${connectivity.vercel.configured ? "text-[#39C98A]" : "text-[#77717C]"}`} />
            <div className="min-w-0">
              <div className="text-[11px] font-medium text-[#77717C]">Vercel Edge</div>
              <div className="text-[12px] font-semibold text-[#F5F1EA] truncate">
                {connectivity.vercel.configured ? "Ready" : "Mock Fallback"}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main Workspace Grid: Workflow Selector + Live Detail */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Workflows List (4 cols) */}
        <div className="lg:col-span-4 space-y-3">
          <div className="p-4 rounded-2xl bg-[#131215] border border-[#242126] space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#77717C]">Workflows</span>
              <span className="text-xs text-[#B7AFBA]">{workflows.length} Total</span>
            </div>

            {/* Filter buttons */}
            <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs">
              {["all", "running", "paused_for_approval", "completed", "failed"].map((f) => (
                <button
                  key={f}
                  onClick={() => setStatusFilter(f)}
                  className={`px-2.5 py-1 rounded-lg capitalize whitespace-nowrap transition ${
                    statusFilter === f
                      ? "bg-[#E8B968]/20 text-[#F5CC7A] border border-[#E8B968]/40 font-medium"
                      : "bg-[#1A181D] text-[#77717C] hover:text-[#B7AFBA] border border-transparent"
                  }`}
                >
                  {f.replace(/_/g, " ")}
                </button>
              ))}
            </div>

            {/* List items */}
            <div className="space-y-2 max-h-[620px] overflow-y-auto pr-1">
              {workflows.length === 0 ? (
                <div className="text-center py-10 text-[#77717C] text-xs">
                  No workflows found. Click &quot;New Multi-Agent Workflow&quot; to begin.
                </div>
              ) : (
                workflows.map((wf) => {
                  const isSelected = selectedWf?.id === wf.id;
                  return (
                    <div
                      key={wf.id}
                      onClick={() => setSelectedWf(wf)}
                      className={`p-3.5 rounded-xl border cursor-pointer transition ${
                        isSelected
                          ? "bg-[#1D1B22] border-[#E8B968]/50 shadow-[0_0_12px_rgba(232,185,105,0.08)]"
                          : "bg-[#17151A] border-[#242126] hover:border-[#38333D] hover:bg-[#1A181F]"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2 mb-1.5">
                        <h3 className="text-xs font-semibold text-[#F5F1EA] truncate">{wf.title}</h3>
                        {getStatusBadge(wf.status)}
                      </div>

                      <div className="flex items-center justify-between text-[11px] text-[#77717C]">
                        <span>Stage: <strong className="text-[#B7AFBA] font-normal">{wf.current_stage.replace(/_/g, " ")}</strong></span>
                        <span className="capitalize">{wf.mode} {wf.is_dry_run && "(Dry-Run)"}</span>
                      </div>

                      <div className="mt-2.5 flex items-center gap-1.5">
                        <div className="flex-1 h-1.5 rounded-full bg-[#100F12] overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-[#E8B968] to-[#39C98A] transition-all"
                            style={{
                              width: `${(wf.completed_stages.length / 24) * 100}%`,
                            }}
                          />
                        </div>
                        <span className="text-[10px] text-[#77717C] font-mono">
                          {wf.completed_stages.length}/24
                        </span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Selected Workflow Command Center (8 cols) */}
        <div className="lg:col-span-8 space-y-4">
          {selectedWf ? (
            <>
              {/* Active Workflow Header Card */}
              <div className="p-5 rounded-2xl bg-[#131215] border border-[#242126] space-y-4">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-[#242126] pb-4">
                  <div>
                    <div className="flex items-center gap-3">
                      <h2 className="text-lg font-bold text-[#F5F1EA] tracking-tight">{selectedWf.title}</h2>
                      {getStatusBadge(selectedWf.status)}
                      {selectedWf.is_dry_run && (
                        <span className="px-2 py-0.5 rounded text-[11px] bg-[#4D7CFE]/15 text-[#7DA4FF] border border-[#4D7CFE]/30 font-mono">
                          DRY RUN
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-[#8A8490] mt-1">
                      Mode: <span className="capitalize text-[#F5F1EA] font-medium">{selectedWf.mode}</span> • ID:{" "}
                      <span className="font-mono text-[#77717C]">{selectedWf.id}</span>
                    </p>
                  </div>

                  {/* Actions Bar */}
                  <div className="flex items-center gap-2">
                    {selectedWf.status === "paused_for_approval" && (
                      <button
                        onClick={() => setShowApprovalModal(true)}
                        disabled={actionLoading}
                        className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-[#E8B968] text-[#0B0A0C] font-bold text-xs hover:brightness-110 transition shadow-[0_0_10px_rgba(232,185,105,0.25)]"
                      >
                        <ShieldAlert className="w-3.5 h-3.5" />
                        Resolve Gate Approval
                      </button>
                    )}

                    {selectedWf.status === "failed" && selectedWf.error_state?.can_retry && (
                      <button
                        onClick={handleRetry}
                        disabled={actionLoading}
                        className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-[#39C98A]/20 border border-[#39C98A]/40 text-[#39C98A] font-semibold text-xs hover:bg-[#39C98A]/30 transition"
                      >
                        <RotateCw className="w-3.5 h-3.5" />
                        Safe Retry Stage
                      </button>
                    )}

                    {selectedWf.mode === "manual" && selectedWf.status === "running" && (
                      <button
                        onClick={handleAdvance}
                        disabled={actionLoading}
                        className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-[#4D7CFE] text-white font-semibold text-xs hover:bg-[#3B6BE8] transition shadow-[0_0_10px_rgba(77,124,254,0.3)]"
                      >
                        <Play className="w-3.5 h-3.5" />
                        Advance Next Stage
                      </button>
                    )}

                    {selectedWf.status !== "completed" && selectedWf.status !== "cancelled" && (
                      <button
                        onClick={() => setShowCancelModal(true)}
                        disabled={actionLoading}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#1B191E] border border-[#2B2730] text-[#EB5757] hover:bg-[#EB5757]/10 text-xs transition"
                      >
                        <XCircle className="w-3.5 h-3.5" />
                        Cancel
                      </button>
                    )}
                  </div>
                </div>

                {/* Gate Alert Banner if Paused */}
                {selectedWf.status === "paused_for_approval" && (
                  <div className="p-4 rounded-xl bg-gradient-to-r from-[#E8B968]/15 via-[#E8B968]/5 to-transparent border border-[#E8B968]/40 flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-[#E8B968]/20 text-[#F5CC7A]">
                        <Lock className="w-5 h-5" />
                      </div>
                      <div>
                        <h4 className="text-xs font-bold text-[#F5CC7A] uppercase tracking-wider">
                          Human Approval Gate Reached: {selectedWf.current_stage.replace(/_/g, " ")}
                        </h4>
                        <p className="text-xs text-[#D8CFDC] mt-0.5">
                          Autonomous execution halted. Platform policy strictly requires owner review before proceeding.
                        </p>
                      </div>
                    </div>
                    <button
                      onClick={() => setShowApprovalModal(true)}
                      className="px-3 py-1.5 rounded-lg bg-[#E8B968] text-[#0B0A0C] font-bold text-xs whitespace-nowrap hover:brightness-110 transition"
                    >
                      Review & Approve
                    </button>
                  </div>
                )}

                {/* Failure Banner if Failed */}
                {selectedWf.status === "failed" && selectedWf.error_state && (
                  <div className="p-4 rounded-xl bg-[#EB5757]/10 border border-[#EB5757]/30 space-y-1.5">
                    <div className="flex items-center gap-2 text-[#EB5757] font-semibold text-xs">
                      <AlertTriangle className="w-4 h-4" />
                      Execution Halted at Stage: {selectedWf.error_state.stage}
                    </div>
                    <p className="text-xs text-[#F29C9C] font-mono">{selectedWf.error_state.error}</p>
                    <div className="text-[11px] text-[#C47D7D] flex items-center gap-2 pt-1">
                      <span>Policy:</span>
                      <strong className="text-white font-normal">{selectedWf.error_state.retry_guidance || (selectedWf.error_state.can_retry ? "Safe to retry" : "Blind retry forbidden")}</strong>
                    </div>
                  </div>
                )}

                {/* 24-Stage Pipeline Visualizer */}
                <div className="space-y-3 pt-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-[#F5F1EA]">24-Stage Pipeline Progression</span>
                    <span className="text-[#8A8490]">{selectedWf.completed_stages.length} of 24 completed</span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 text-xs">
                    {STAGES_CANONICAL.map((stage, idx) => {
                      const isCompleted = selectedWf.completed_stages.some(
                        (cs) => typeof cs === "object" && cs !== null && "stage" in cs && cs.stage === stage.id
                      );
                      const isCurrent = selectedWf.current_stage === stage.id && selectedWf.status !== "completed";

                      let stageBg = "bg-[#17151A] border-[#242126] text-[#77717C]";
                      if (isCompleted) {
                        stageBg = "bg-[#39C98A]/10 border-[#39C98A]/30 text-[#39C98A]";
                      } else if (isCurrent) {
                        stageBg = "bg-[#E8B968]/15 border-[#E8B968]/50 text-[#F5CC7A] ring-1 ring-[#E8B968]/30";
                      }

                      return (
                        <div
                          key={stage.id}
                          className={`p-2.5 rounded-xl border flex flex-col justify-between min-h-[64px] transition ${stageBg}`}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] font-mono opacity-70">#{idx + 1}</span>
                            {isCompleted ? (
                              <CheckCircle2 className="w-3.5 h-3.5 text-[#39C98A]" />
                            ) : isCurrent ? (
                              <span className="w-2 h-2 rounded-full bg-[#E8B968] animate-ping" />
                            ) : stage.isGate ? (
                              <Lock className="w-3 h-3 text-[#77717C]" />
                            ) : null}
                          </div>

                          <div>
                            <div className="font-semibold text-[11px] truncate leading-tight mt-1">{stage.label}</div>
                            <div className="text-[10px] opacity-70 truncate">{stage.agent}</div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Step Audit Telemetry History */}
              <div className="p-5 rounded-2xl bg-[#131215] border border-[#242126] space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-[#77717C]">
                    Immutable Step Audit Telemetry
                  </h3>
                  <span className="text-xs text-[#8A8490] font-mono">
                    {selectedWf.step_records?.length || 0} Records
                  </span>
                </div>

                <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1">
                  {!selectedWf.step_records || selectedWf.step_records.length === 0 ? (
                    <div className="text-center py-6 text-[#77717C] text-xs">
                      No telemetry records recorded yet.
                    </div>
                  ) : (
                    selectedWf.step_records.map((step) => (
                      <div
                        key={step.id}
                        className="p-3 rounded-xl bg-[#17151A] border border-[#242126] text-xs space-y-1.5"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span
                              className={`w-2 h-2 rounded-full ${
                                step.status === "completed"
                                  ? "bg-[#39C98A]"
                                  : step.status === "failed"
                                  ? "bg-[#EB5757]"
                                  : "bg-[#E8B968]"
                              }`}
                            />
                            <strong className="text-[#F5F1EA] font-semibold">{step.stage.replace(/_/g, " ")}</strong>
                            {step.is_dry_run && (
                              <span className="text-[9px] px-1 py-0.2 rounded bg-[#4D7CFE]/20 text-[#7DA4FF]">
                                SIMULATED
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 text-[#77717C] text-[11px] font-mono">
                            <span>{step.duration_ms}ms</span>
                            <span>•</span>
                            <span>{new Date(step.created_at).toLocaleTimeString()}</span>
                          </div>
                        </div>

                        {step.error_message && (
                          <div className="text-[11px] text-[#EB5757] font-mono bg-[#EB5757]/10 p-2 rounded">
                            {step.error_message}
                          </div>
                        )}

                        {step.output_snapshot && (
                          <pre className="text-[10px] text-[#B7AFBA] font-mono bg-[#111013] p-2 rounded overflow-x-auto max-h-24">
                            {JSON.stringify(step.output_snapshot, null, 2)}
                          </pre>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="p-12 rounded-2xl bg-[#131215] border border-[#242126] text-center space-y-3">
              <GitBranch className="w-8 h-8 text-[#77717C] mx-auto opacity-50" />
              <h3 className="text-sm font-semibold text-[#F5F1EA]">No Workflow Selected</h3>
              <p className="text-xs text-[#77717C] max-w-sm mx-auto">
                Select an existing workflow on the left or create a new multi-agent pipeline to begin end-to-end execution.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Modal: Create Workflow */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl bg-[#17151A] border border-[#2B2730] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#242126] pb-3">
              <h3 className="text-sm font-bold text-[#F5F1EA]">Launch Autonomous Pipeline Workflow</h3>
              <button onClick={() => setShowCreateModal(false)} className="text-[#77717C] hover:text-[#F5F1EA]">
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateWorkflow} className="space-y-4 text-xs">
              <div>
                <label className="block text-[#B7AFBA] font-medium mb-1">Workflow Title *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. End-to-End Modernization: Apex Architectural Design"
                  value={formTitle}
                  onChange={(e) => setFormTitle(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-[#111013] border border-[#242126] text-[#F5F1EA] focus:outline-none focus:border-[#E8B968]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[#B7AFBA] font-medium mb-1">Target Company</label>
                  <input
                    type="text"
                    placeholder="e.g. Apex Architectural Design"
                    value={formCompany}
                    onChange={(e) => setFormCompany(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl bg-[#111013] border border-[#242126] text-[#F5F1EA] focus:outline-none focus:border-[#E8B968]"
                  />
                </div>
                <div>
                  <label className="block text-[#B7AFBA] font-medium mb-1">Target Domain</label>
                  <input
                    type="text"
                    placeholder="e.g. apexdesign.example.com"
                    value={formDomain}
                    onChange={(e) => setFormDomain(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl bg-[#111013] border border-[#242126] text-[#F5F1EA] focus:outline-none focus:border-[#E8B968]"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[#B7AFBA] font-medium mb-1">Execution Mode</label>
                <div className="grid grid-cols-3 gap-2">
                  {(["supervised", "manual", "dry_run"] as WorkflowExecutionMode[]).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setFormMode(mode)}
                      className={`p-2.5 rounded-xl border text-center transition capitalize ${
                        formMode === mode
                          ? "bg-[#E8B968]/20 border-[#E8B968] text-[#F5CC7A] font-semibold"
                          : "bg-[#111013] border-[#242126] text-[#77717C] hover:text-[#B7AFBA]"
                      }`}
                    >
                      {mode.replace(/_/g, " ")}
                    </button>
                  ))}
                </div>
                <p className="text-[11px] text-[#77717C] mt-1.5">
                  {formMode === "supervised" && "Supervised: Safe stages run automatically; pauses unconditionally at Human Approval Gates."}
                  {formMode === "manual" && "Manual: Runs strictly one stage at a time, requiring explicit owner advance command."}
                  {formMode === "dry_run" && "Dry-Run: Simulates entire 24 stages with ZERO real side effects (no real emails or repos)."}
                </p>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="dryRunToggle"
                  checked={formDryRun}
                  onChange={(e) => setFormDryRun(e.target.checked)}
                  className="rounded bg-[#111013] border-[#242126] text-[#E8B968] focus:ring-0"
                />
                <label htmlFor="dryRunToggle" className="text-[#B7AFBA] select-none cursor-pointer">
                  Simulation Dry-Run (Never send real emails, publish real Git commits, or deploy to Vercel)
                </label>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#242126]">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 rounded-xl bg-[#111013] text-[#B7AFBA] hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading || !formTitle.trim()}
                  className="px-4 py-2 rounded-xl bg-gradient-to-r from-[#E8B968] to-[#C99846] text-[#0B0A0C] font-bold shadow-[0_0_12px_rgba(232,185,105,0.25)] hover:brightness-110 disabled:opacity-50"
                >
                  {actionLoading ? "Creating..." : "Create Workflow"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Human Approval Gate Resolution */}
      {showApprovalModal && selectedWf && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl bg-[#17151A] border border-[#2B2730] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#242126] pb-3">
              <div className="flex items-center gap-2 text-[#F5CC7A]">
                <ShieldAlert className="w-5 h-5" />
                <h3 className="text-sm font-bold text-[#F5F1EA]">Gate Review: {selectedWf.current_stage.replace(/_/g, " ")}</h3>
              </div>
              <button onClick={() => setShowApprovalModal(false)} className="text-[#77717C] hover:text-[#F5F1EA]">
                ✕
              </button>
            </div>

            <p className="text-xs text-[#B7AFBA]">
              As the authenticated agency owner, grant or reject progression past this security gate.
            </p>

            <div>
              <label className="block text-xs text-[#B7AFBA] font-medium mb-1">Owner Review Notes</label>
              <textarea
                rows={3}
                placeholder="Optional decision rationale or feedback..."
                value={approvalNotes}
                onChange={(e) => setApprovalNotes(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-[#111013] border border-[#242126] text-[#F5F1EA] text-xs focus:outline-none focus:border-[#E8B968]"
              />
            </div>

            <div className="flex items-center justify-between pt-3 border-t border-[#242126]">
              <button
                type="button"
                onClick={() => handleApproval("rejected")}
                disabled={actionLoading}
                className="px-4 py-2 rounded-xl bg-[#EB5757]/15 border border-[#EB5757]/40 text-[#EB5757] font-semibold text-xs hover:bg-[#EB5757]/25 transition"
              >
                Reject Gate
              </button>

              <button
                type="button"
                onClick={() => handleApproval("approved")}
                disabled={actionLoading}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-[#39C98A] to-[#2FB578] text-[#0B0A0C] font-bold text-xs shadow-[0_0_12px_rgba(57,201,138,0.25)] hover:brightness-110 transition"
              >
                Approve & Proceed
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Cancel Workflow */}
      {showCancelModal && selectedWf && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl bg-[#17151A] border border-[#2B2730] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#242126] pb-3">
              <h3 className="text-sm font-bold text-[#F5F1EA]">Cancel Workflow</h3>
              <button onClick={() => setShowCancelModal(false)} className="text-[#77717C] hover:text-[#F5F1EA]">
                ✕
              </button>
            </div>

            <p className="text-xs text-[#B7AFBA]">
              Are you sure you want to cancel &quot;{selectedWf.title}&quot;? Active background runs will be terminated.
            </p>

            <div>
              <label className="block text-xs text-[#B7AFBA] font-medium mb-1">Cancellation Reason</label>
              <input
                type="text"
                placeholder="e.g. Client paused engagement"
                value={cancelReason}
                onChange={(e) => setCancelReason(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-[#111013] border border-[#242126] text-[#F5F1EA] text-xs focus:outline-none focus:border-[#E8B968]"
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#242126]">
              <button
                type="button"
                onClick={() => setShowCancelModal(false)}
                className="px-4 py-2 rounded-xl bg-[#111013] text-[#B7AFBA] text-xs"
              >
                Dismiss
              </button>
              <button
                type="button"
                onClick={handleCancel}
                disabled={actionLoading}
                className="px-4 py-2 rounded-xl bg-[#EB5757] text-white font-bold text-xs hover:brightness-110 transition"
              >
                Confirm Cancellation
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
