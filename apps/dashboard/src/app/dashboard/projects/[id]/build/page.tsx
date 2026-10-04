"use client";

import { useEffect, useState, use, useCallback } from "react";
import Link from "next/link";
import {
  api,
  type ProjectDetail,
  type WebsiteBuildSessionDetail,
  type WebsiteBuildSession,
  type WebsiteGeneration,
  type WebsiteGenerationDetail,
  type WebsiteSpecification,
  type DesignBlueprint,
  type DesignBlueprintDetail,
  type WebsiteDesignBlueprint,
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
  Cpu,
  Compass,
  Palette,
  AlignLeft,
  HelpCircle,
  Code,
  Layout,
  ExternalLink,
  Box,
  Sliders,
  Eye,
  Type,
  Maximize2,
  CheckSquare,
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
  const [generations, setGenerations] = useState<WebsiteGeneration[]>([]);
  const [selectedGeneration, setSelectedGeneration] = useState<WebsiteGenerationDetail | null>(null);
  const [activeSpecTab, setActiveSpecTab] = useState<"pages" | "navigation" | "design" | "content" | "raw">("pages");

  // Phase 6.3 Design Blueprint State
  const [blueprints, setBlueprints] = useState<DesignBlueprint[]>([]);
  const [selectedBlueprint, setSelectedBlueprint] = useState<DesignBlueprintDetail | null>(null);
  const [blueprintLoading, setBlueprintLoading] = useState(false);
  const [activeBlueprintTab, setActiveBlueprintTab] = useState<"tokens" | "components" | "pages" | "assets" | "a11y" | "raw">("tokens");

  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [genLoading, setGenLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const loadBlueprintsForGen = useCallback(async (generationId: string) => {
    try {
      const bpList = await api.websiteBuilder.listBlueprints(generationId);
      setBlueprints(bpList.items);
      if (bpList.items.length > 0) {
        const bpDetail = await api.websiteBuilder.getBlueprint(bpList.items[0].id);
        setSelectedBlueprint(bpDetail);
      } else {
        setSelectedBlueprint(null);
      }
    } catch {
      setBlueprints([]);
      setSelectedBlueprint(null);
    }
  }, []);

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
        const [detail, gensList] = await Promise.all([
          api.websiteBuilder.getSession(targetSessionId),
          api.websiteBuilder.listGenerations(targetSessionId),
        ]);
        setActiveSession(detail);
        setGenerations(gensList.items);

        // Auto-select latest generation if available
        if (gensList.items.length > 0) {
          const genDetail = await api.websiteBuilder.getGeneration(gensList.items[0].id);
          setSelectedGeneration(genDetail);
          await loadBlueprintsForGen(genDetail.id);
        } else {
          setSelectedGeneration(null);
          setBlueprints([]);
          setSelectedBlueprint(null);
        }
      } else {
        setActiveSession(null);
        setGenerations([]);
        setSelectedGeneration(null);
        setBlueprints([]);
        setSelectedBlueprint(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load build workspace data.");
    } finally {
      setLoading(false);
    }
  }, [projectId, loadBlueprintsForGen]);


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
        setSuccessMessage("Session moved to READY. Specification generation is now unlocked.");
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

  const handleTriggerGeneration = async () => {
    if (!activeSession) return;
    try {
      setGenLoading(true);
      setError(null);
      setSuccessMessage(null);
      await api.websiteBuilder.createGeneration(activeSession.id);
      setSuccessMessage("AI Website Specification generated successfully.");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate website specification.");
    } finally {
      setGenLoading(false);
    }
  };

  const handleSelectGeneration = async (genId: string) => {
    try {
      setActionLoading(true);
      const detail = await api.websiteBuilder.getGeneration(genId);
      setSelectedGeneration(detail);
      await loadBlueprintsForGen(detail.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load generation detail.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleSelectSession = async (sessionId: string) => {
    try {
      setActionLoading(true);
      const [detail, gensList] = await Promise.all([
        api.websiteBuilder.getSession(sessionId),
        api.websiteBuilder.listGenerations(sessionId),
      ]);
      setActiveSession(detail);
      setGenerations(gensList.items);
      if (gensList.items.length > 0) {
        const genDetail = await api.websiteBuilder.getGeneration(gensList.items[0].id);
        setSelectedGeneration(genDetail);
        await loadBlueprintsForGen(genDetail.id);
      } else {
        setSelectedGeneration(null);
        setBlueprints([]);
        setSelectedBlueprint(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session details.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleTriggerBlueprint = async () => {
    if (!selectedGeneration || selectedGeneration.status !== "completed") return;
    try {
      setBlueprintLoading(true);
      setError(null);
      setSuccessMessage(null);
      const newBp = await api.websiteBuilder.createBlueprint(selectedGeneration.id);
      setSuccessMessage(`AI Design Blueprint v${newBp.blueprint_version} generated successfully.`);
      await loadBlueprintsForGen(selectedGeneration.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate design blueprint.");
    } finally {
      setBlueprintLoading(false);
    }
  };

  const handleSelectBlueprint = async (blueprintId: string) => {
    try {
      setActionLoading(true);
      const detail = await api.websiteBuilder.getBlueprint(blueprintId);
      setSelectedBlueprint(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load blueprint details.");
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
      case "generating":
      case "validating":
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

  const spec: WebsiteSpecification | undefined = selectedGeneration?.specification || undefined;
  const bp: WebsiteDesignBlueprint | undefined = selectedBlueprint?.blueprint || undefined;


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
              Website Build &amp; Specification Workspace
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
            <span className="text-[#77717C]">Project:</span>
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

      {/* Strict Architectural Boundary Notice */}
      <div className="p-4 rounded-xl bg-[#1B191E] border border-[#E8B968]/20 flex items-start gap-3">
        <Info className="w-5 h-5 text-[#E8B968] flex-shrink-0 mt-0.5" />
        <div className="text-xs text-[#A9A4AE] space-y-1">
          <p className="font-semibold text-[#F5F1EA]">
            Phase 6.2 AI Website Generation Engine — Structured Specification Boundary
          </p>
          <p>
            Generates validated, comprehensive <span className="text-[#E8B968] font-mono">WebsiteSpecification</span> data anchored to your approved PRD.
            In strict compliance with architectural boundaries, executable source code generation (React, Next.js, HTML, CSS), GitHub repository commits, and Vercel deployments remain deferred to subsequent phases.
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
        {/* Left 2 Columns: Active Session, Generation Controls, and Specification Viewer */}
        <div className="lg:col-span-2 space-y-6">
          {/* Active Build Session Card */}
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

                {/* State Machine Transitions */}
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
                  </div>
                </div>

                {/* AI Specification Generation Trigger (Phase 6.2) */}
                <div className="p-5 rounded-xl bg-gradient-to-r from-[#1B191E] to-[#16141A] border border-[#E8B968]/30 space-y-4">
                  <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Sparkles className="w-4 h-4 text-[#E8B968]" />
                        <h3 className="text-sm font-bold text-[#F5F1EA]">
                          AI Website Specification Engine
                        </h3>
                      </div>
                      <p className="text-xs text-[#77717C]">
                        Generate a comprehensive, structured WebsiteSpecification from PRD v{project.prd_version}.
                      </p>
                    </div>

                    {activeSession.status === "ready" ? (
                      <button
                        onClick={handleTriggerGeneration}
                        disabled={genLoading || actionLoading}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[#E8B968] hover:bg-[#F5CC7A] text-[#141216] text-xs font-bold transition-all shadow-md disabled:opacity-50"
                      >
                        <Cpu className={`w-4 h-4 ${genLoading ? "animate-spin" : ""}`} />
                        <span>{genLoading ? "Generating Specification..." : "Generate Website Specification"}</span>
                      </button>
                    ) : (
                      <div className="text-xs text-[#77717C] bg-[#141216] px-3 py-1.5 rounded-lg border border-[#242126]">
                        Requires session status: <span className="text-[#39C98A] font-semibold">READY</span>
                      </div>
                    )}
                  </div>
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

          {/* AI Website Specification Viewer (Phase 6.2 Output) */}
          {selectedGeneration && (
            <div className="p-6 rounded-2xl bg-[#131215] border border-[#242126] space-y-6">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-[#242126] pb-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-[#E8B968] uppercase tracking-wider">
                      AI Website Specification
                    </span>
                    <span className="text-xs text-[#77717C]">•</span>
                    <span className="text-xs font-mono text-[#F5F1EA]">
                      Generation v{selectedGeneration.generation_version}
                    </span>
                  </div>
                  <h3 className="text-lg font-bold text-[#F5F1EA] mt-0.5">
                    {spec?.project_name || selectedGeneration.project_name || "Website Specification"}
                  </h3>
                </div>

                <div className="flex items-center gap-2">
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-xs font-bold border uppercase ${getStatusBadge(
                      selectedGeneration.status
                    )}`}
                  >
                    {selectedGeneration.status}
                  </span>
                  <div className="px-3 py-1 rounded-xl bg-[#1B191E] border border-[#242126] text-xs font-mono text-[#77717C]">
                    {selectedGeneration.provider}/{selectedGeneration.model}
                  </div>
                </div>
              </div>

              {spec ? (
                <div className="space-y-6">
                  {/* Specification Overview Chips */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                    <div className="p-3 rounded-xl bg-[#1B191E] border border-[#242126]">
                      <span className="text-[10px] text-[#77717C] uppercase font-semibold">Goal</span>
                      <p className="text-[#F5F1EA] mt-1 line-clamp-2">{spec.website_goal}</p>
                    </div>
                    <div className="p-3 rounded-xl bg-[#1B191E] border border-[#242126]">
                      <span className="text-[10px] text-[#77717C] uppercase font-semibold">Target Audience</span>
                      <p className="text-[#F5F1EA] mt-1 line-clamp-2">{spec.target_audience}</p>
                    </div>
                    <div className="p-3 rounded-xl bg-[#1B191E] border border-[#242126]">
                      <span className="text-[10px] text-[#77717C] uppercase font-semibold">Primary CTA</span>
                      <p className="text-[#E8B968] font-bold mt-1">{spec.primary_cta}</p>
                    </div>
                  </div>

                  {/* Navigation Tabs */}
                  <div className="flex items-center gap-2 border-b border-[#242126] pb-2 text-xs">
                    <button
                      onClick={() => setActiveSpecTab("pages")}
                      className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                        activeSpecTab === "pages"
                          ? "bg-[#E8B968] text-[#141216] font-bold"
                          : "text-[#77717C] hover:text-[#F5F1EA]"
                      }`}
                    >
                      Pages &amp; Sections ({spec.pages.length})
                    </button>
                    <button
                      onClick={() => setActiveSpecTab("navigation")}
                      className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                        activeSpecTab === "navigation"
                          ? "bg-[#E8B968] text-[#141216] font-bold"
                          : "text-[#77717C] hover:text-[#F5F1EA]"
                      }`}
                    >
                      Navigation Map ({spec.navigation.length})
                    </button>
                    <button
                      onClick={() => setActiveSpecTab("design")}
                      className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                        activeSpecTab === "design"
                          ? "bg-[#E8B968] text-[#141216] font-bold"
                          : "text-[#77717C] hover:text-[#F5F1EA]"
                      }`}
                    >
                      Design System
                    </button>
                    <button
                      onClick={() => setActiveSpecTab("content")}
                      className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                        activeSpecTab === "content"
                          ? "bg-[#E8B968] text-[#141216] font-bold"
                          : "text-[#77717C] hover:text-[#F5F1EA]"
                      }`}
                    >
                      Content Strategy ({spec.content_strategy?.length || 0})
                    </button>
                    <button
                      onClick={() => setActiveSpecTab("raw")}
                      className={`px-3 py-1.5 rounded-lg font-medium transition-colors ${
                        activeSpecTab === "raw"
                          ? "bg-[#E8B968] text-[#141216] font-bold"
                          : "text-[#77717C] hover:text-[#F5F1EA]"
                      }`}
                    >
                      Raw Spec JSON
                    </button>
                  </div>

                  {/* Tab Content: Pages & Sections */}
                  {activeSpecTab === "pages" && (
                    <div className="space-y-4">
                      {spec.pages.map((p) => (
                        <div
                          key={p.page_id}
                          className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-3"
                        >
                          <div className="flex items-center justify-between border-b border-[#242126] pb-2">
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-[#F5F1EA] text-sm">{p.name}</span>
                              <span className="font-mono text-xs text-[#E8B968] bg-[#E8B968]/10 px-2 py-0.5 rounded">
                                {p.path}
                              </span>
                            </div>
                            <span className="text-[10px] text-[#77717C] uppercase font-semibold">
                              {p.sections.length} Sections
                            </span>
                          </div>

                          <div className="text-xs text-[#77717C] space-y-1">
                            <p><span className="text-[#F5F1EA]">SEO Title:</span> {p.seo_title}</p>
                            <p><span className="text-[#F5F1EA]">Purpose:</span> {p.purpose}</p>
                          </div>

                          <div className="space-y-2 pt-2 border-t border-[#242126]/60">
                            <span className="text-[10px] font-semibold text-[#77717C] uppercase tracking-wider block">
                              Sections Structure
                            </span>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                              {p.sections.map((s) => (
                                <div
                                  key={s.section_id}
                                  className="p-3 rounded-lg bg-[#141216] border border-[#242126] text-xs space-y-1"
                                >
                                  <div className="flex items-center justify-between">
                                    <span className="font-semibold text-[#F5F1EA]">{s.heading}</span>
                                    <span className="text-[10px] font-mono text-[#E8B968] uppercase">
                                      {s.type}
                                    </span>
                                  </div>
                                  <p className="text-[11px] text-[#77717C]">{s.purpose}</p>
                                  <div className="flex flex-wrap gap-1 pt-1">
                                    {s.components.map((c) => (
                                      <span
                                        key={c}
                                        className="text-[9px] font-mono bg-[#242126] text-[#A9A4AE] px-1.5 py-0.5 rounded"
                                      >
                                        {c}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Tab Content: Navigation Map */}
                  {activeSpecTab === "navigation" && (
                    <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-3">
                      <table className="w-full text-left text-xs">
                        <thead>
                          <tr className="border-b border-[#242126] text-[#77717C]">
                            <th className="pb-2 font-semibold">Order</th>
                            <th className="pb-2 font-semibold">Label</th>
                            <th className="pb-2 font-semibold">Path</th>
                            <th className="pb-2 font-semibold">Visibility</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#242126]">
                          {spec.navigation.map((n) => (
                            <tr key={n.path} className="text-[#F5F1EA]">
                              <td className="py-2.5 font-mono text-[#77717C]">{n.order}</td>
                              <td className="py-2.5 font-semibold">{n.label}</td>
                              <td className="py-2.5 font-mono text-[#E8B968]">{n.path}</td>
                              <td className="py-2.5 capitalize text-[#39C98A]">{n.visibility}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Tab Content: Design System */}
                  {activeSpecTab === "design" && (
                    <div className="space-y-4 text-xs">
                      {/* Visual Direction */}
                      <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-2">
                        <span className="text-[10px] text-[#77717C] uppercase font-semibold">Visual Direction</span>
                        <p className="text-[#F5F1EA] text-sm">{spec.design_system.visual_direction}</p>
                      </div>

                      {/* Color Palette */}
                      <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-3">
                        <span className="text-[10px] text-[#77717C] uppercase font-semibold">Color Palette</span>
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                          {Object.entries(spec.design_system.color_palette).map(([name, hex]) => (
                            <div key={name} className="flex items-center gap-2.5 p-2 rounded-lg bg-[#141216] border border-[#242126]">
                              <div
                                className="w-5 h-5 rounded-md border border-white/10 flex-shrink-0"
                                style={{ backgroundColor: hex }}
                              />
                              <div>
                                <p className="font-semibold text-[#F5F1EA] capitalize text-[11px]">{name}</p>
                                <p className="font-mono text-[9px] text-[#77717C]">{hex}</p>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Typography */}
                      <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-2">
                        <span className="text-[10px] text-[#77717C] uppercase font-semibold">Typography</span>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div>
                            <span className="text-[#77717C]">Heading Family:</span>
                            <p className="font-bold text-[#F5F1EA]">{spec.design_system.typography.heading_family}</p>
                          </div>
                          <div>
                            <span className="text-[#77717C]">Body Family:</span>
                            <p className="font-bold text-[#F5F1EA]">{spec.design_system.typography.body_family}</p>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Tab Content: Content Strategy */}
                  {activeSpecTab === "content" && (
                    <div className="space-y-3">
                      {spec.content_strategy && spec.content_strategy.length > 0 ? (
                        spec.content_strategy.map((c, i) => (
                          <div
                            key={i}
                            className="p-3.5 rounded-xl bg-[#1B191E] border border-[#242126] text-xs flex justify-between items-center"
                          >
                            <div>
                              <p className="font-semibold text-[#F5F1EA]">{c.content_type}</p>
                              <p className="text-[11px] text-[#77717C]">
                                Page: <span className="font-mono text-[#E8B968]">{c.page}</span> • Section:{" "}
                                <span className="font-mono text-[#A9A4AE]">{c.section}</span>
                              </p>
                              {c.notes && <p className="text-[10px] text-[#77717C] mt-1">{c.notes}</p>}
                            </div>
                            <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#242126] text-[#E8B968]">
                              {c.source}
                            </span>
                          </div>
                        ))
                      ) : (
                        <div className="p-6 rounded-xl bg-[#1B191E] border border-[#242126] text-center text-xs text-[#77717C]">
                          No specific content strategy items mapped.
                        </div>
                      )}
                    </div>
                  )}

                  {/* Tab Content: Raw JSON */}
                  {activeSpecTab === "raw" && (
                    <pre className="p-4 rounded-xl bg-[#0C0B0D] border border-[#242126] text-[11px] font-mono text-[#A9A4AE] overflow-x-auto max-h-[450px]">
                      {JSON.stringify(spec, null, 2)}
                    </pre>
                  )}
                </div>
              ) : (
                <div className="p-6 rounded-xl bg-[#1B191E] border border-[#242126] text-center text-xs text-[#77717C]">
                  {selectedGeneration.status === "failed" ? (
                    <span className="text-red-400">Generation failed: {selectedGeneration.error_message}</span>
                  ) : (
                    <span>Specification is being processed...</span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* AI Design Blueprint Generation Trigger (Phase 6.3) */}
          {selectedGeneration && selectedGeneration.status === "completed" && (
            <div className="p-5 rounded-xl bg-gradient-to-r from-[#1B191E] via-[#161B22] to-[#141216] border border-cyan-500/30 space-y-4">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Box className="w-4 h-4 text-cyan-400" />
                    <h3 className="text-sm font-bold text-[#F5F1EA]">
                      AI Design System + Site Architecture Engine
                    </h3>
                  </div>
                  <p className="text-xs text-[#77717C]">
                    Synthesize design tokens, component taxonomy, section blueprints, and accessibility rules from Spec v{selectedGeneration.generation_version}.
                  </p>
                </div>

                <button
                  onClick={handleTriggerBlueprint}
                  disabled={blueprintLoading || actionLoading}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-[#0C1017] text-xs font-bold transition-all shadow-md disabled:opacity-50 shrink-0"
                >
                  <Box className={`w-4 h-4 ${blueprintLoading ? "animate-spin" : ""}`} />
                  <span>{blueprintLoading ? "Generating Blueprint..." : "Generate Design Blueprint"}</span>
                </button>
              </div>
            </div>
          )}

          {/* AI Design Blueprint Viewer (Phase 6.3 Output) */}
          {selectedBlueprint && (
            <div className="p-6 rounded-2xl bg-[#131215] border border-cyan-500/30 space-y-6">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-[#242126] pb-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">
                      AI Design Blueprint
                    </span>
                    <span className="text-xs text-[#77717C]">•</span>
                    <span className="text-xs font-mono text-[#F5F1EA]">
                      Blueprint v{selectedBlueprint.blueprint_version}
                    </span>
                    <span className="text-xs text-[#77717C]">•</span>
                    <span className="text-[11px] text-[#77717C]">
                      Anchored to Spec v{selectedBlueprint.source_generation_version}
                    </span>
                  </div>
                  <h3 className="text-lg font-bold text-[#F5F1EA] mt-0.5">
                    {bp?.project_name || selectedBlueprint.project_name || "Design System Blueprint"}
                  </h3>
                </div>

                <div className="flex items-center gap-2">
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-xs font-bold border uppercase ${getStatusBadge(
                      selectedBlueprint.status
                    )}`}
                  >
                    {selectedBlueprint.status}
                  </span>
                  {selectedBlueprint.specification_artifact_id && (
                    <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono bg-cyan-950/40 text-cyan-300 border border-cyan-700/40">
                      ARTIFACT RECORDED
                    </span>
                  )}
                </div>
              </div>

              {/* Informational Scope Badge */}
              <div className="p-3 rounded-xl bg-cyan-950/20 border border-cyan-500/20 text-xs text-cyan-200/80 flex items-center gap-2">
                <Info className="w-4 h-4 text-cyan-400 shrink-0" />
                <span>
                  Implementation-ready design system blueprint specifying tokens, component catalog, and responsive layouts. Not a finished website or executable code.
                </span>
              </div>

              {bp ? (
                <div className="space-y-6">
                  {/* Metric Chips */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                    <div className="p-3 rounded-xl bg-[#1B191E] border border-[#242126]">
                      <span className="text-[10px] text-[#77717C] uppercase font-semibold">Components</span>
                      <p className="text-sm font-bold text-[#F5F1EA] mt-0.5">{bp.component_taxonomy?.length ?? 0}</p>
                    </div>
                    <div className="p-3 rounded-xl bg-[#1B191E] border border-[#242126]">
                      <span className="text-[10px] text-[#77717C] uppercase font-semibold">Pages Planned</span>
                      <p className="text-sm font-bold text-[#F5F1EA] mt-0.5">{bp.pages?.length ?? 0}</p>
                    </div>
                    <div className="p-3 rounded-xl bg-[#1B191E] border border-[#242126]">
                      <span className="text-[10px] text-[#77717C] uppercase font-semibold">Asset Specs</span>
                      <p className="text-sm font-bold text-[#F5F1EA] mt-0.5">{bp.asset_requirements?.length ?? 0}</p>
                    </div>
                    <div className="p-3 rounded-xl bg-[#1B191E] border border-[#242126]">
                      <span className="text-[10px] text-[#77717C] uppercase font-semibold">Breakpoints</span>
                      <p className="text-sm font-bold text-[#F5F1EA] mt-0.5">{bp.responsive_breakpoints?.length ?? 0}</p>
                    </div>
                  </div>

                  {/* Blueprint Tabs */}
                  <div className="flex flex-wrap gap-2 border-b border-[#242126] pb-3 text-xs font-semibold">
                    {[
                      { id: "tokens", label: "Design Tokens", icon: Palette },
                      { id: "components", label: `Component Taxonomy (${bp.component_taxonomy?.length ?? 0})`, icon: Box },
                      { id: "pages", label: `Page Architecture (${bp.pages?.length ?? 0})`, icon: Layout },
                      { id: "assets", label: `Asset Requirements (${bp.asset_requirements?.length ?? 0})`, icon: Eye },
                      { id: "a11y", label: "Accessibility & Motion", icon: ShieldCheck },
                      { id: "raw", label: "Blueprint JSON", icon: Code },
                    ].map((tab) => {
                      const Icon = tab.icon;
                      const isActive = activeBlueprintTab === tab.id;
                      return (
                        <button
                          key={tab.id}
                          onClick={() => setActiveBlueprintTab(tab.id as any)}
                          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border transition-all ${
                            isActive
                              ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                              : "bg-[#1B191E] text-[#77717C] border-[#242126] hover:text-[#A9A4AE]"
                          }`}
                        >
                          <Icon className="w-3.5 h-3.5" />
                          <span>{tab.label}</span>
                        </button>
                      );
                    })}
                  </div>

                  {/* Tab 1: Design Tokens */}
                  {activeBlueprintTab === "tokens" && bp.design_tokens && (
                    <div className="space-y-6">
                      {/* Color Palette */}
                      <div className="space-y-2">
                        <h4 className="text-xs font-bold text-[#F5F1EA] uppercase tracking-wider">Color System</h4>
                        <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-3">
                          {Object.entries(bp.design_tokens.colors || {}).map(([key, val]) => (
                            <div key={key} className="p-3 rounded-xl bg-[#1B191E] border border-[#242126] space-y-2">
                              <div
                                className="w-full h-8 rounded-lg border border-white/10 shadow-inner"
                                style={{ backgroundColor: val }}
                              />
                              <div>
                                <p className="text-[11px] font-semibold text-[#F5F1EA] capitalize">{key}</p>
                                <p className="text-[10px] font-mono text-[#77717C]">{val}</p>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Typography System */}
                      <div className="space-y-2">
                        <h4 className="text-xs font-bold text-[#F5F1EA] uppercase tracking-wider">Typography System</h4>
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                          <div className="p-3 rounded-xl bg-[#1B191E] border border-[#242126]">
                            <span className="text-[10px] text-[#77717C] uppercase font-semibold">Heading Font</span>
                            <p className="text-xs font-bold text-[#F5F1EA] mt-1">{bp.design_tokens.typography.heading_font}</p>
                            <p className="text-[10px] text-[#77717C] mt-1">Weights: {bp.design_tokens.typography.heading_weights?.join(", ")}</p>
                          </div>
                          <div className="p-3 rounded-xl bg-[#1B191E] border border-[#242126]">
                            <span className="text-[10px] text-[#77717C] uppercase font-semibold">Body Font</span>
                            <p className="text-xs font-bold text-[#F5F1EA] mt-1">{bp.design_tokens.typography.body_font}</p>
                            <p className="text-[10px] text-[#77717C] mt-1">Weights: {bp.design_tokens.typography.body_weights?.join(", ")}</p>
                          </div>
                          <div className="p-3 rounded-xl bg-[#1B191E] border border-[#242126]">
                            <span className="text-[10px] text-[#77717C] uppercase font-semibold">Mono Font</span>
                            <p className="text-xs font-mono font-bold text-[#F5F1EA] mt-1">{bp.design_tokens.typography.mono_font}</p>
                          </div>
                        </div>
                      </div>

                      {/* Spacing, Radius, Container */}
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                        <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-2">
                          <span className="text-[10px] text-[#77717C] uppercase font-semibold">Spacing Scale</span>
                          <div className="flex flex-wrap gap-1.5 pt-1">
                            {Object.entries(bp.design_tokens.spacing || {}).map(([k, v]) => (
                              <span key={k} className="px-2 py-0.5 rounded bg-[#242126] text-[10px] font-mono text-[#F5F1EA]">
                                {k}: {v}
                              </span>
                            ))}
                          </div>
                        </div>
                        <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-2">
                          <span className="text-[10px] text-[#77717C] uppercase font-semibold">Border Radius</span>
                          <div className="flex flex-wrap gap-1.5 pt-1">
                            {Object.entries(bp.design_tokens.radius || {}).map(([k, v]) => (
                              <span key={k} className="px-2 py-0.5 rounded bg-[#242126] text-[10px] font-mono text-[#F5F1EA]">
                                {k}: {v}
                              </span>
                            ))}
                          </div>
                        </div>
                        <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-2">
                          <span className="text-[10px] text-[#77717C] uppercase font-semibold">Container</span>
                          <div className="space-y-1 text-xs text-[#A9A4AE] pt-1">
                            <p>Max Width: <strong className="text-[#F5F1EA]">{bp.design_tokens.container?.max_width}</strong></p>
                            <p>Gutters: <strong className="text-[#F5F1EA]">{bp.design_tokens.container?.gutters}</strong></p>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Tab 2: Component Taxonomy */}
                  {activeBlueprintTab === "components" && (
                    <div className="space-y-3">
                      {bp.component_taxonomy?.map((comp) => (
                        <div key={comp.component_id} className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-2">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="font-mono font-bold text-xs text-cyan-300">{comp.component_id}</span>
                              <span className="text-xs font-bold text-[#F5F1EA]">{comp.component_name}</span>
                            </div>
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-[#242126] text-[#A9A4AE]">
                              {comp.category}
                            </span>
                          </div>
                          <p className="text-xs text-[#A9A4AE]">{comp.purpose}</p>
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-2 text-[11px] text-[#77717C]">
                            <div>
                              <span className="font-semibold text-[#A9A4AE]">Variants: </span>
                              <span className="font-mono">{comp.variants?.join(", ") || "default"}</span>
                            </div>
                            <div>
                              <span className="font-semibold text-[#A9A4AE]">Responsive: </span>
                              <span>{comp.responsive_behavior}</span>
                            </div>
                            <div className="sm:col-span-2">
                              <span className="font-semibold text-[#A9A4AE]">A11y: </span>
                              <span>{comp.accessibility_requirements?.join("; ") || "Standard"}</span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Tab 3: Page Architecture */}
                  {activeBlueprintTab === "pages" && (
                    <div className="space-y-4">
                      {bp.pages?.map((p) => (
                        <div key={p.page_id} className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-3">
                          <div className="flex items-center justify-between">
                            <div>
                              <h4 className="text-sm font-bold text-[#F5F1EA]">{p.name}</h4>
                              <span className="font-mono text-xs text-cyan-400">{p.route}</span>
                            </div>
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#242126] text-[#A9A4AE]">
                              {p.layout_type}
                            </span>
                          </div>
                          <p className="text-xs text-[#A9A4AE]">{p.purpose}</p>

                          <div className="space-y-2 pt-2">
                            <span className="text-[10px] font-semibold text-[#77717C] uppercase tracking-wider block">
                              Sections Hierarchy ({p.sections?.length ?? 0})
                            </span>
                            <div className="grid grid-cols-1 gap-2">
                              {p.sections?.map((sec, idx) => (
                                <div key={sec.section_id} className="p-2.5 rounded-lg bg-[#141216] border border-[#242126] text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                                  <div>
                                    <span className="font-mono text-cyan-300 mr-2">#{idx + 1} {sec.section_id}</span>
                                    <span className="text-[#A9A4AE]">({sec.section_type})</span>
                                    <p className="text-[11px] text-[#77717C] mt-0.5">{sec.purpose}</p>
                                  </div>
                                  <div className="flex flex-wrap gap-1">
                                    {sec.component_refs?.map((ref) => (
                                      <span key={ref} className="px-1.5 py-0.5 rounded bg-cyan-950/60 text-cyan-300 border border-cyan-800/40 text-[10px] font-mono">
                                        {ref}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Tab 4: Asset Requirements */}
                  {activeBlueprintTab === "assets" && (
                    <div className="space-y-3">
                      {bp.asset_requirements?.map((asset) => (
                        <div key={asset.asset_id} className="p-3 rounded-xl bg-[#1B191E] border border-[#242126] text-xs space-y-1">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="font-mono font-bold text-cyan-300">{asset.asset_id}</span>
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-[#242126] text-[#A9A4AE]">
                                {asset.type}
                              </span>
                            </div>
                            <span className="text-[10px] font-mono text-[#77717C]">
                              Page: {asset.page} • Section: {asset.section}
                            </span>
                          </div>
                          <p className="text-xs text-[#A9A4AE]">{asset.purpose}</p>
                          <div className="flex flex-wrap gap-3 pt-1 text-[11px] text-[#77717C]">
                            {asset.dimensions && <span>Dimensions: <strong className="text-[#F5F1EA]">{asset.dimensions}</strong></span>}
                            {asset.aspect_ratio && <span>Aspect: <strong className="text-[#F5F1EA]">{asset.aspect_ratio}</strong></span>}
                            <span>Alt Requirement: <span className="italic text-[#A9A4AE]">{asset.accessibility_alt_requirement}</span></span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Tab 5: Accessibility & Motion */}
                  {activeBlueprintTab === "a11y" && (
                    <div className="space-y-4 text-xs">
                      {bp.accessibility && (
                        <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] space-y-3">
                          <h4 className="font-bold text-[#F5F1EA] uppercase tracking-wider text-[11px]">Accessibility Blueprint</h4>
                          <div className="space-y-2 text-[#A9A4AE]">
                            <div>
                              <span className="font-semibold text-[#F5F1EA]">Focus & Contrast: </span>
                              <span>{bp.accessibility.focus_behavior} • {bp.accessibility.color_contrast_requirement}</span>
                            </div>
                            <div>
                              <span className="font-semibold text-[#F5F1EA]">Keyboard Navigation: </span>
                              <span>{bp.accessibility.keyboard_navigation?.join("; ")}</span>
                            </div>
                            <div>
                              <span className="font-semibold text-[#F5F1EA]">Semantic & Headings: </span>
                              <span>{bp.accessibility.heading_hierarchy?.join("; ")}</span>
                            </div>
                            <div>
                              <span className="font-semibold text-[#F5F1EA]">Reduced Motion: </span>
                              <span>{bp.accessibility.reduced_motion_behavior}</span>
                            </div>
                          </div>
                        </div>
                      )}

                      {bp.interactions && bp.interactions.length > 0 && (
                        <div className="space-y-2">
                          <h4 className="font-bold text-[#F5F1EA] uppercase tracking-wider text-[11px]">Interactions & Motion</h4>
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {bp.interactions.map((inter) => (
                              <div key={inter.interaction_id} className="p-3 rounded-xl bg-[#1B191E] border border-[#242126] space-y-1">
                                <span className="font-mono text-cyan-300 font-bold">{inter.interaction_id}</span>
                                <p className="text-[#F5F1EA] font-semibold">{inter.name}</p>
                                <p className="text-[11px] text-[#77717C]">Trigger: {inter.trigger} • Duration: {inter.duration}</p>
                                <p className="text-[11px] text-[#A9A4AE]">Behavior: {inter.behavior}</p>
                                <p className="text-[10px] text-[#77717C]">Reduced motion: {inter.reduced_motion_behavior}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Tab 6: Raw JSON */}
                  {activeBlueprintTab === "raw" && (
                    <pre className="p-4 rounded-xl bg-[#0C0B0D] border border-[#242126] text-[11px] font-mono text-[#A9A4AE] overflow-x-auto max-h-[450px]">
                      {JSON.stringify(bp, null, 2)}
                    </pre>
                  )}
                </div>
              ) : (
                <div className="p-6 rounded-xl bg-[#1B191E] border border-[#242126] text-center text-xs text-[#77717C]">
                  {selectedBlueprint.status === "failed" ? (
                    <span className="text-red-400">Blueprint generation failed: {selectedBlueprint.error_message}</span>
                  ) : (
                    <span>Blueprint is being processed...</span>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Column: Generation History, Blueprint History & Session Baseline */}
        <div className="space-y-6">
          {/* Blueprint History Card (Phase 6.3) */}
          <div className="p-6 rounded-2xl bg-[#131215] border border-cyan-500/30 space-y-4">
            <div className="flex items-center justify-between border-b border-[#242126] pb-3">
              <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">
                Blueprint History ({blueprints.length})
              </span>
              <Box className="w-4 h-4 text-cyan-400" />
            </div>

            {blueprints.length > 0 ? (
              <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
                {blueprints.map((b) => {
                  const isSelected = selectedBlueprint?.id === b.id;
                  return (
                    <button
                      key={b.id}
                      onClick={() => handleSelectBlueprint(b.id)}
                      className={`w-full text-left p-3 rounded-xl border transition-all text-xs ${
                        isSelected
                          ? "bg-[#1B191E] border-cyan-500"
                          : "bg-[#1B191E]/50 border-[#242126] hover:border-cyan-500/40"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-[#F5F1EA]">Blueprint v{b.blueprint_version}</span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase border ${getStatusBadge(
                            b.status
                          )}`}
                        >
                          {b.status}
                        </span>
                      </div>
                      <div className="flex justify-between items-center mt-2 text-[10px] text-[#77717C]">
                        <span>{new Date(b.created_at).toLocaleDateString()}</span>
                        <span className="font-mono">Spec v{b.source_generation_version}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] text-center text-xs text-[#77717C]">
                No design blueprints generated yet.
              </div>
            )}
          </div>

          {/* Generation History Card */}
          <div className="p-6 rounded-2xl bg-[#131215] border border-[#242126] space-y-4">
            <div className="flex items-center justify-between border-b border-[#242126] pb-3">
              <span className="text-xs font-semibold text-[#77717C] uppercase tracking-wider">
                Specification History ({generations.length})
              </span>
              <Cpu className="w-4 h-4 text-[#E8B968]" />
            </div>


            {generations.length > 0 ? (
              <div className="space-y-2 max-h-[320px] overflow-y-auto pr-1">
                {generations.map((g) => {
                  const isSelected = selectedGeneration?.id === g.id;
                  return (
                    <button
                      key={g.id}
                      onClick={() => handleSelectGeneration(g.id)}
                      className={`w-full text-left p-3 rounded-xl border transition-all text-xs ${
                        isSelected
                          ? "bg-[#1B191E] border-[#E8B968]"
                          : "bg-[#1B191E]/50 border-[#242126] hover:border-[#38333D]"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-[#F5F1EA]">Spec v{g.generation_version}</span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase border ${getStatusBadge(
                            g.status
                          )}`}
                        >
                          {g.status}
                        </span>
                      </div>
                      <div className="flex justify-between items-center mt-2 text-[10px] text-[#77717C]">
                        <span>{new Date(g.created_at).toLocaleDateString()}</span>
                        <span className="font-mono">{g.provider}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="p-4 rounded-xl bg-[#1B191E] border border-[#242126] text-center text-xs text-[#77717C]">
                No specification generations yet.
              </div>
            )}
          </div>

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
              <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
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
                        <span className="font-bold text-[#F5F1EA]">Session v{s.build_version}</span>
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
