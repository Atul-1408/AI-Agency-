"use client";

import { useEffect, useState, use, useCallback } from "react";
import Link from "next/link";
import {
  api,
  type ProjectDetail,
  type WebsiteBuildSessionDetail,
  type WebsiteBuildSession,
} from "@/lib/api";
import {
  ArrowLeft,
  Hammer,
  ShieldCheck,
  Sparkles,
  AlertTriangle,
  Clock,
  Layers,
  FileText,
  CheckCircle2,
  XCircle,
  PauseCircle,
  PlayCircle,
  History,
  Info,
  Calendar,
  Lock,
} from "lucide-react";

export default function WebsiteBuildWorkspacePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const resolvedParams = use(params);
  const projectId = resolvedParams.id;

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [sessions, setSessions] = useState<WebsiteBuildSession[]>([]);
  const [activeSession, setActiveSession] = useState<WebsiteBuildSessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [projData, sessionListData] = await Promise.all([
        api.projects.get(projectId),
        api.websiteBuilder.listSessions(projectId),
      ]);
      setProject(projData);
      setSessions(sessionListData.items);

      // Find current active session or most recent session
      const active = sessionListData.items.find((s) =>
        ["created", "planned", "ready", "in_progress", "paused"].includes(s.status)
      );
      const targetSessionId = active ? active.id : sessionListData.items[0]?.id;

      if (targetSessionId) {
        const detail = await api.websiteBuilder.getSession(targetSessionId);
        setActiveSession(detail);
      } else {
        setActiveSession(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load build workspace data.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCreateSession = async () => {
    try {
      setActionLoading(true);
      setError(null);
      setSuccessMessage(null);
      await api.websiteBuilder.createSession(projectId);
      setSuccessMessage("Build session created successfully.");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create build session.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleTransition = async (action: "plan" | "ready" | "pause" | "cancel") => {
    if (!activeSession) return;
    try {
      setActionLoading(true);
      setError(null);
      setSuccessMessage(null);

      if (action === "plan") {
        await api.websiteBuilder.planSession(activeSession.id, "Owner initiated planning phase");
        setSuccessMessage("Session moved to PLANNED.");
      } else if (action === "ready") {
        await api.websiteBuilder.readySession(activeSession.id, "Owner confirmed ready state");
        setSuccessMessage("Session moved to READY.");
      } else if (action === "pause") {
        await api.websiteBuilder.pauseSession(activeSession.id, "Owner requested pause");
        setSuccessMessage("Session moved to PAUSED.");
      } else if (action === "cancel") {
        const confirmed = window.confirm("Are you sure you want to cancel this build session?");
        if (!confirmed) {
          setActionLoading(false);
          return;
        }
        await api.websiteBuilder.cancelSession(activeSession.id, "Owner initiated cancellation");
        setSuccessMessage("Session CANCELLED.");
      }
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to update build session: ${action}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleSelectSession = async (sessionId: string) => {
    try {
      setActionLoading(true);
      const detail = await api.websiteBuilder.getSession(sessionId);
      setActiveSession(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session details.");
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="p-16 text-center text-[#77717C]">
        <div className="w-7 h-7 border-2 border-[#E8B968] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-sm">Loading Website Build Workspace...</p>
      </div>
    );
  }

  if (error && !project) {
    return (
      <div className="p-12 text-center rounded-2xl bg-[#131215] border border-red-500/20 max-w-xl mx-auto my-8">
        <AlertTriangle className="w-8 h-8 text-red-400 mx-auto mb-3" />
        <h3 className="text-lg font-semibold text-[#F5F1EA]">Unable to Load Workspace</h3>
        <p className="text-sm text-[#77717C] mt-2">{error}</p>
        <Link
          href={`/dashboard/projects/${projectId}`}
          className="inline-flex items-center gap-2 mt-6 px-4 py-2 rounded-xl bg-[#1B191E] border border-[#242126] text-sm text-[#F5F1EA] hover:border-[#E8B968]/40 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Project Detail
        </Link>
      </div>
    );
  }

  if (!project) return null;

  const isReadyForBuild = project.project_status === "ready_for_build" || project.project_status === "in_build";
  const hasApprovedPRD = Boolean(project.approved_prd_id);

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "created":
        return "bg-blue-500/10 text-blue-400 border-blue-500/30";
      case "planned":
        return "bg-purple-500/10 text-purple-400 border-purple-500/30";
      case "ready":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
      case "in_progress":
        return "bg-amber-500/10 text-amber-400 border-amber-500/30";
      case "paused":
        return "bg-orange-500/10 text-orange-400 border-orange-500/30";
      case "completed":
        return "bg-green-500/10 text-green-400 border-green-500/30";
      case "failed":
        return "bg-red-500/10 text-red-400 border-red-500/30";
      case "cancelled":
        return "bg-neutral-500/10 text-neutral-400 border-neutral-500/30";
      default:
        return "bg-neutral-500/10 text-neutral-400 border-neutral-500/30";
    }
  };

  return (
    <div className="space-y-8 max-w-7xl mx-auto pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-[#242126] pb-6">
        <div className="flex items-center gap-3">
          <Link
            href={`/dashboard/projects/${projectId}`}
            className="w-9 h-9 rounded-xl bg-[#131215] border border-[#242126] flex items-center justify-center text-[#77717C] hover:text-[#F5F1EA] hover:border-[#38333D] transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-[#77717C]">Projects</span>
              <span className="text-xs text-[#77717C]">/</span>
              <span className="text-xs font-mono text-[#E8B968]">{project.project_slug}</span>
              <span className="text-xs text-[#77717C]">/</span>
              <span className="text-xs text-[#F5F1EA]">Build Workspace</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-[#F5F1EA] mt-0.5 flex items-center gap-2">
              <Hammer className="w-5 h-5 text-[#E8B968]" />
              Website Build Workspace Foundation
            </h1>
          </div>
        </div>

        {/* Status Indicators */}
        <div className="flex items-center gap-3 self-start sm:self-center">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-[#39C98A]/10 border border-[#39C98A]/30 text-xs text-[#39C98A] font-medium">
            <ShieldCheck className="w-4 h-4" />
            <span>PRD v{project.prd_version}</span>
            <span className="text-[#39C98A]/40">•</span>
            <span className="uppercase">{project.prd_summary?.status || "Approved"}</span>
          </div>

          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-[#1B191E] border border-[#242126] text-xs text-[#F5F1EA]">
            <span className="text-[#77717C]">Project Status:</span>
            <span className="font-semibold uppercase tracking-wider text-[#E8B968]">
              {project.project_status.replace(/_/g, " ")}
            </span>
          </div>
        </div>
      </div>

      {/* Messages */}
      {error && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-sm text-red-400 flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {successMessage && (
        <div className="p-4 rounded-xl bg-green-500/10 border border-green-500/20 text-sm text-green-400 flex items-center gap-3">
          <CheckCircle2 className="w-5 h-5 flex-shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Phase 6.1 Strict Architectural Boundary Notice */}
      <div className="p-4 rounded-xl bg-[#1B191E] border border-[#E8B968]/20 flex items-start gap-3">
        <Info className="w-5 h-5 text-[#E8B968] flex-shrink-0 mt-0.5" />
        <div className="text-xs text-[#A9A4AE] space-y-1">
          <p className="font-semibold text-[#F5F1EA]">
            Phase 6.1 Workspace Foundation &amp; Immutability Controls
          </p>
          <p>
            This workspace provides deterministic session state management, PRD version anchoring, and artifact tracking.
            In strict compliance with Phase 6.1 boundaries, automatic code generation, GitHub repository creation, and Vercel deployments are deferred to subsequent phases.
          </p>
        </div>
      </div>

      {/* Gate Verification Banner if not READY_FOR_BUILD */}
      {!isReadyForBuild && (
        <div className="p-6 rounded-2xl bg-[#131215] border border-amber-500/30 space-y-3">
          <div className="flex items-center gap-2 text-amber-400 font-semibold text-sm">
            <Lock className="w-5 h-5" />
            <span>Project Not Ready For Build Sessions</span>
          </div>
          <p className="text-xs text-[#77717C]">
            A build session requires the project to be in <span className="text-[#F5F1EA] font-mono">READY_FOR_BUILD</span> status with an approved PRD.
            Current status is <span className="text-amber-400 font-mono">{project.project_status}</span>.
          </p>
        </div>
      )}

      {/* Main Grid: Session Controls + Detail */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Active Session / Session Actions */}
        <div className="lg:col-span-2 space-y-6">
          <div className="p-6 rounded-2xl bg-[#131215] border border-[#242126] space-y-6">
            <div className="flex items-center justify-between border-b border-[#242126] pb-4">
              <div>
                <span className="text-xs font-semibold text-[#77717C] uppercase tracking-wider">
                  Active Build Session
                </span>
                <h2 className="text-lg font-bold text-[#F5F1EA] mt-0.5">
                  {activeSession ? `Build Session #${activeSession.build_version}` : "No Active Session"}
                </h2>
              </div>

              {/* Controlled Create Button */}
              {isReadyForBuild && hasApprovedPRD && !activeSession && (
                <button
                  onClick={handleCreateSession}
                  disabled={actionLoading}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[#E8B968] hover:bg-[#F5CC7A] text-[#141216] text-xs font-bold transition-colors disabled:opacity-50"
                >
                  <Hammer className="w-4 h-4" />
                  <span>{actionLoading ? "Creating..." : "Create Build Session"}</span>
                </button>
              )}
            </div>

            {activeSession ? (
              <div className="space-y-6">
                {/* Status and Info Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126]">
                    <span className="text-[10px] text-[#77717C] uppercase font-semibold">Status</span>
                    <div className="mt-1">
                      <span
                        className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-bold border uppercase ${getStatusBadge(
                          activeSession.status
                        )}`}
                      >
                        {activeSession.status}
                      </span>
                    </div>
                  </div>

                  <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126]">
                    <span className="text-[10px] text-[#77717C] uppercase font-semibold">Build Version</span>
                    <p className="text-sm font-mono font-bold text-[#F5F1EA] mt-1">
                      v{activeSession.build_version}
                    </p>
                  </div>

                  <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126]">
                    <span className="text-[10px] text-[#77717C] uppercase font-semibold">PRD Snapshot</span>
                    <p className="text-sm font-mono font-bold text-[#E8B968] mt-1">
                      PRD v{project.prd_version}
                    </p>
                  </div>

                  <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126]">
                    <span className="text-[10px] text-[#77717C] uppercase font-semibold">Created</span>
                    <p className="text-xs text-[#A9A4AE] mt-1">
                      {new Date(activeSession.created_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>

                {/* Session ID / Timestamps Detail */}
                <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-2 text-xs">
                  <div className="flex justify-between items-center text-[#77717C]">
                    <span>Session ID:</span>
                    <span className="font-mono text-[#F5F1EA]">{activeSession.id}</span>
                  </div>
                  <div className="flex justify-between items-center text-[#77717C]">
                    <span>Last Updated:</span>
                    <span className="text-[#A9A4AE]">
                      {new Date(activeSession.updated_at).toLocaleString()}
                    </span>
                  </div>
                  {activeSession.started_at && (
                    <div className="flex justify-between items-center text-[#77717C]">
                      <span>Started At:</span>
                      <span className="text-[#A9A4AE]">
                        {new Date(activeSession.started_at).toLocaleString()}
                      </span>
                    </div>
                  )}
                  {activeSession.completed_at && (
                    <div className="flex justify-between items-center text-[#77717C]">
                      <span>Completed At:</span>
                      <span className="text-[#A9A4AE]">
                        {new Date(activeSession.completed_at).toLocaleString()}
                      </span>
                    </div>
                  )}
                  {activeSession.failure_reason && (
                    <div className="flex justify-between items-center text-red-400">
                      <span>Failure Reason:</span>
                      <span>{activeSession.failure_reason}</span>
                    </div>
                  )}
                </div>

                {/* State Machine Action Controls */}
                <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-3">
                  <span className="text-xs font-semibold text-[#77717C] uppercase tracking-wider block">
                    Session Lifecycle Transitions
                  </span>
                  <div className="flex flex-wrap items-center gap-3">
                    {activeSession.status === "created" && (
                      <button
                        onClick={() => handleTransition("plan")}
                        disabled={actionLoading}
                        className="px-3.5 py-1.5 rounded-lg bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/40 text-purple-300 text-xs font-semibold transition-colors disabled:opacity-50"
                      >
                        Plan Build Session (CREATED → PLANNED)
                      </button>
                    )}

                    {activeSession.status === "planned" && (
                      <button
                        onClick={() => handleTransition("ready")}
                        disabled={actionLoading}
                        className="px-3.5 py-1.5 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 text-emerald-300 text-xs font-semibold transition-colors disabled:opacity-50"
                      >
                        Mark Ready (PLANNED → READY)
                      </button>
                    )}

                    {activeSession.status === "in_progress" && (
                      <button
                        onClick={() => handleTransition("pause")}
                        disabled={actionLoading}
                        className="px-3.5 py-1.5 rounded-lg bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/40 text-orange-300 text-xs font-semibold transition-colors disabled:opacity-50"
                      >
                        Pause Session (IN_PROGRESS → PAUSED)
                      </button>
                    )}

                    {["created", "planned", "ready", "paused"].includes(activeSession.status) && (
                      <button
                        onClick={() => handleTransition("cancel")}
                        disabled={actionLoading}
                        className="px-3.5 py-1.5 rounded-lg bg-neutral-800 hover:bg-red-500/20 border border-neutral-700 hover:border-red-500/40 text-neutral-300 hover:text-red-400 text-xs font-semibold transition-colors disabled:opacity-50"
                      >
                        Cancel Session
                      </button>
                    )}

                    {["completed", "failed", "cancelled"].includes(activeSession.status) && (
                      <span className="text-xs text-[#77717C] italic">
                        This session is in terminal state ({activeSession.status}). Its state is immutable.
                      </span>
                    )}
                  </div>
                </div>

                {/* Build Artifacts */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-[#77717C] uppercase tracking-wider">
                      Session Artifacts ({activeSession.artifacts?.length || 0})
                    </span>
                    <span className="text-[10px] text-[#77717C]">Controlled References Only</span>
                  </div>

                  {activeSession.artifacts && activeSession.artifacts.length > 0 ? (
                    <div className="space-y-2">
                      {activeSession.artifacts.map((artifact) => (
                        <div
                          key={artifact.id}
                          className="p-3.5 rounded-xl bg-[#1B191E] border border-[#242126] flex items-center justify-between text-xs"
                        >
                          <div className="flex items-center gap-3">
                            <FileText className="w-4 h-4 text-[#E8B968]" />
                            <div>
                              <p className="font-semibold text-[#F5F1EA]">{artifact.artifact_name}</p>
                              <p className="text-[10px] text-[#77717C] font-mono">
                                Type: {artifact.artifact_type} • v{artifact.artifact_version}
                              </p>
                            </div>
                          </div>
                          <div className="text-right">
                            <span className="text-[10px] text-[#77717C]">
                              {new Date(artifact.created_at).toLocaleString()}
                            </span>
                            {artifact.content_reference && (
                              <p className="text-[10px] font-mono text-[#E8B968]">
                                {artifact.content_reference}
                              </p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="p-6 rounded-xl bg-[#1B191E] border border-[#242126] text-center text-xs text-[#77717C]">
                      No artifacts recorded for this session yet.
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-8 rounded-xl bg-[#1B191E] border border-[#242126] text-center space-y-3">
                <Hammer className="w-8 h-8 text-[#77717C] mx-auto" />
                <h3 className="text-sm font-semibold text-[#F5F1EA]">No Active Build Session</h3>
                <p className="text-xs text-[#77717C] max-w-sm mx-auto">
                  {isReadyForBuild
                    ? "Click 'Create Build Session' above to initialize a controlled build session anchored to your approved PRD."
                    : "Complete project approval requirements to enable build session initialization."}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Project & Session History */}
        <div className="space-y-6">
          {/* PRD Reference Card */}
          <div className="p-6 rounded-2xl bg-[#131215] border border-[#242126] space-y-4">
            <div className="flex items-center justify-between border-b border-[#242126] pb-3">
              <span className="text-xs font-semibold text-[#77717C] uppercase tracking-wider">
                PRD Baseline
              </span>
              <FileText className="w-4 h-4 text-[#E8B968]" />
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex justify-between items-center text-[#77717C]">
                <span>PRD Version:</span>
                <span className="font-mono text-[#F5F1EA]">v{project.prd_version}</span>
              </div>
              <div className="flex justify-between items-center text-[#77717C]">
                <span>PRD ID:</span>
                <span className="font-mono text-[#E8B968] truncate max-w-[150px]">
                  {project.approved_prd_id}
                </span>
              </div>
              <div className="flex justify-between items-center text-[#77717C]">
                <span>Gate 4 Status:</span>
                <span className="text-[#39C98A] font-semibold">Approved</span>
              </div>
              {project.prd_summary?.title && (
                <div className="pt-2 border-t border-[#242126]">
                  <span className="text-[10px] text-[#77717C] uppercase">PRD Title</span>
                  <p className="text-xs text-[#F5F1EA] font-medium mt-0.5">
                    {project.prd_summary.title}
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Session History Card */}
          <div className="p-6 rounded-2xl bg-[#131215] border border-[#242126] space-y-4">
            <div className="flex items-center justify-between border-b border-[#242126] pb-3">
              <span className="text-xs font-semibold text-[#77717C] uppercase tracking-wider">
                Session History ({sessions.length})
              </span>
              <History className="w-4 h-4 text-[#77717C]" />
            </div>

            {sessions.length > 0 ? (
              <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1">
                {sessions.map((s) => {
                  const isSelected = activeSession?.id === s.id;
                  return (
                    <button
                      key={s.id}
                      onClick={() => handleSelectSession(s.id)}
                      className={`w-full text-left p-3 rounded-xl border transition-all text-xs ${
                        isSelected
                          ? "bg-[#1B191E] border-[#E8B968]"
                          : "bg-[#1B191E]/50 border-[#242126] hover:border-[#38333D]"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-[#F5F1EA]">v{s.build_version}</span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase border ${getStatusBadge(
                            s.status
                          )}`}
                        >
                          {s.status}
                        </span>
                      </div>
                      <div className="flex justify-between items-center mt-2 text-[10px] text-[#77717C]">
                        <span>{new Date(s.created_at).toLocaleDateString()}</span>
                        <span className="font-mono truncate max-w-[100px]">{s.id.slice(0, 8)}...</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] text-center text-xs text-[#77717C]">
                No build sessions recorded yet.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
