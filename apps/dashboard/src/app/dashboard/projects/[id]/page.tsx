"use client";

import { useEffect, useState, use } from "react";
import Link from "next/link";
import {
  api,
  type ProjectDetail,
  type ProjectStatus,
} from "@/lib/api";
import {
  FolderKanban,
  ArrowLeft,
  Building2,
  Globe,
  Mail,
  CheckCircle2,
  Clock,
  Sparkles,
  FileText,
  AlertTriangle,
  Layers,
  ChevronRight,
  ExternalLink,
  ShieldCheck,
  MessageSquare,
  HelpCircle,
  Hash,
  Hammer,
} from "lucide-react";

export default function ProjectDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const resolvedParams = use(params);
  const projectId = resolvedParams.id;

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchDetail = async () => {
      try {
        setLoading(true);
        const data = await api.projects.get(projectId);
        if (mounted) {
          setProject(data);
          setError(null);
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : "Failed to load project details.");
        }
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchDetail();
    return () => {
      mounted = false;
    };
  }, [projectId]);

  if (loading) {
    return (
      <div className="p-16 text-center text-[#77717C]">
        <div className="w-7 h-7 border-2 border-[#E8B968] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-sm">Loading project handoff intelligence...</p>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="p-12 text-center rounded-2xl bg-[#131215] border border-red-500/20 max-w-xl mx-auto my-8">
        <AlertTriangle className="w-8 h-8 text-red-400 mx-auto mb-3" />
        <h3 className="text-lg font-semibold text-[#F5F1EA]">Unable to Load Project</h3>
        <p className="text-sm text-[#77717C] mt-2">{error || "Project not found."}</p>
        <Link
          href="/dashboard/projects"
          className="inline-flex items-center gap-2 mt-6 px-4 py-2 rounded-xl bg-[#1B191E] border border-[#242126] text-sm text-[#F5F1EA] hover:border-[#E8B968]/40 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Projects
        </Link>
      </div>
    );
  }

  const meta = project.phase_metadata || {};
  const sitemap = (meta.sitemap as Array<{ page: string; status?: string }>) || [];
  const openQuestions = (meta.open_questions as Array<Record<string, unknown>>) || [];
  const assumptions = (meta.assumptions as string[]) || [];
  const traceability = (meta.requirement_traceability as Record<string, unknown>) || {};
  const goals = (meta.goals as string[]) || [];

  const createdDate = new Date(project.created_at).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  const updatedDate = new Date(project.updated_at).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="space-y-8 pb-16">
      {/* Top Breadcrumb & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard/projects"
            className="w-9 h-9 rounded-xl bg-[#131215] border border-[#242126] flex items-center justify-center text-[#77717C] hover:text-[#F5F1EA] hover:border-[#38333D] transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-[#77717C]">Projects</span>
              <span className="text-xs text-[#77717C]">/</span>
              <span className="text-xs font-mono text-[#E8B968]">{project.project_slug}</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-[#F5F1EA] mt-0.5">
              {project.project_name}
            </h1>
          </div>
        </div>

        {/* Phase 6 Handoff Readiness Pill */}
        <div className="flex items-center gap-3 self-start sm:self-center">
          <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-[#39C98A]/10 border border-[#39C98A]/30 text-xs text-[#39C98A] font-medium">
            <ShieldCheck className="w-4 h-4" />
            <span>Gate 4 Approved</span>
            <span className="text-[#39C98A]/40">•</span>
            <span>PRD v{project.prd_version}</span>
          </div>

          <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-[#E8B968]/10 border border-[#E8B968]/30 text-xs text-[#F5CC7A] font-medium">
            <Sparkles className="w-4 h-4 text-[#E8B968]" />
            <span>Phase 6 Handoff Ready</span>
          </div>

          {project.project_status === "ready_for_build" && (
            <Link
              href={`/dashboard/projects/${project.id}/build`}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[#E8B968] hover:bg-[#F5CC7A] text-[#141216] text-xs font-bold transition-colors shadow-sm"
            >
              <Hammer className="w-4 h-4" />
              <span>Open Build Workspace</span>
            </Link>
          )}
        </div>
      </div>

      {/* Grid: Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Project Card */}
        <div className="p-6 rounded-2xl bg-[#131215] border border-[#242126] space-y-4">
          <div className="flex items-center justify-between border-b border-[#242126] pb-3">
            <span className="text-xs font-semibold text-[#77717C] uppercase tracking-wider">
              Project Specification
            </span>
            <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-[#1B191E] border border-[#242126] text-[#39C98A]">
              {project.project_status}
            </span>
          </div>
          <div className="space-y-2.5 text-xs">
            <div className="flex justify-between">
              <span className="text-[#77717C]">Project Name:</span>
              <span className="text-[#F5F1EA] font-medium">{project.project_name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#77717C]">Slug:</span>
              <span className="font-mono text-[#F5CC7A]">{project.project_slug}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#77717C]">Created:</span>
              <span className="text-[#B7AFBA]">{createdDate}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#77717C]">Last Updated:</span>
              <span className="text-[#B7AFBA]">{updatedDate}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#77717C]">Source:</span>
              <span className="text-[#B7AFBA]">{project.project_source}</span>
            </div>
          </div>
        </div>

        {/* Business Intelligence Card */}
        <div className="p-6 rounded-2xl bg-[#131215] border border-[#242126] space-y-4">
          <div className="flex items-center justify-between border-b border-[#242126] pb-3">
            <span className="text-xs font-semibold text-[#77717C] uppercase tracking-wider">
              Client & Business
            </span>
            <Building2 className="w-4 h-4 text-[#77717C]" />
          </div>
          <div className="space-y-2.5 text-xs">
            <div className="flex justify-between">
              <span className="text-[#77717C]">Company:</span>
              <span className="text-[#F5F1EA] font-medium">
                {project.business_name || (meta.business_name as string) || "Unknown"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#77717C]">Domain:</span>
              <span className="text-[#F5CC7A]">
                {project.business_domain || (meta.business_domain as string) || "N/A"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#77717C]">Industry:</span>
              <span className="text-[#B7AFBA]">
                {project.business_type || (project.lead_info?.industry as string) || "Services"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#77717C]">City:</span>
              <span className="text-[#B7AFBA]">
                {(project.lead_info?.city as string) || "N/A"}
              </span>
            </div>
          </div>
        </div>

        {/* PRD Reference Card */}
        <div className="p-6 rounded-2xl bg-[#131215] border border-[#242126] space-y-4">
          <div className="flex items-center justify-between border-b border-[#242126] pb-3">
            <span className="text-xs font-semibold text-[#77717C] uppercase tracking-wider">
              Approved PRD (Gate 4)
            </span>
            <FileText className="w-4 h-4 text-[#E8B968]" />
          </div>
          <div className="space-y-2.5 text-xs">
            <div className="flex justify-between">
              <span className="text-[#77717C]">PRD Version:</span>
              <span className="font-mono text-[#F5F1EA] font-medium">v{project.prd_version}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#77717C]">Status:</span>
              <span className="text-[#39C98A] font-medium">
                {project.prd_summary?.status || "APPROVED"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#77717C]">Approved By:</span>
              <span className="text-[#B7AFBA]">
                {project.prd_summary?.approved_by || (meta.approved_by as string) || "Agency Owner"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#77717C]">Approved At:</span>
              <span className="text-[#B7AFBA]">
                {project.prd_summary?.approved_at
                  ? new Date(project.prd_summary.approved_at).toLocaleDateString()
                  : "Recorded"}
              </span>
            </div>
            <div className="pt-2">
              <Link
                href={`/dashboard/client-intelligence/${project.conversation_id}/prd`}
                className="inline-flex items-center gap-1.5 text-xs text-[#E8B968] hover:underline"
              >
                <span>View Full Approved PRD</span>
                <ExternalLink className="w-3 h-3" />
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* Main Tabs / Sections */}
      <div className="space-y-6">
        {/* Executive Summary */}
        <div className="p-6 rounded-2xl bg-[#131215] border border-[#242126] space-y-3">
          <h3 className="text-sm font-semibold text-[#F5F1EA] flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-[#E8B968]" />
            PRD Executive Summary
          </h3>
          <p className="text-xs text-[#B7AFBA] leading-relaxed">
            {(meta.executive_summary as string) ||
              project.prd_summary?.executive_summary ||
              "Approved specifications ready for Phase 6 build handoff."}
          </p>
        </div>

        {/* Sitemap & Pages Planned */}
        <div className="p-6 rounded-2xl bg-[#131215] border border-[#242126] space-y-4">
          <h3 className="text-sm font-semibold text-[#F5F1EA] flex items-center gap-2">
            <Layers className="w-4 h-4 text-[#39C98A]" />
            Planned Website Structure (Sitemap)
          </h3>
          {sitemap.length === 0 ? (
            <p className="text-xs text-[#77717C]">No specific pages specified in PRD.</p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
              {sitemap.map((pageObj, idx) => {
                const name = typeof pageObj === "string" ? pageObj : pageObj.page;
                return (
                  <div
                    key={idx}
                    className="p-3 rounded-xl bg-[#1B191E] border border-[#242126] text-xs font-mono text-[#F5F1EA] flex items-center gap-2"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-[#39C98A]" />
                    <span className="truncate">{name}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Goals and Open Questions */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Goals */}
          <div className="p-6 rounded-2xl bg-[#131215] border border-[#242126] space-y-3">
            <h3 className="text-sm font-semibold text-[#F5F1EA] flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-[#39C98A]" />
              Project Goals & Deliverables
            </h3>
            {goals.length === 0 ? (
              <p className="text-xs text-[#77717C]">Standard web presence transformation.</p>
            ) : (
              <ul className="space-y-2 text-xs text-[#B7AFBA]">
                {goals.map((goal, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="text-[#39C98A] mt-0.5">•</span>
                    <span>{goal}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Open Questions */}
          <div className="p-6 rounded-2xl bg-[#131215] border border-[#242126] space-y-3">
            <h3 className="text-sm font-semibold text-[#F5F1EA] flex items-center gap-2">
              <HelpCircle className="w-4 h-4 text-[#E8B968]" />
              Open Questions & Assumptions
            </h3>
            {openQuestions.length === 0 && assumptions.length === 0 ? (
              <p className="text-xs text-[#39C98A]">All core requirements confirmed by owner.</p>
            ) : (
              <div className="space-y-2 text-xs">
                {openQuestions.map((q, idx) => (
                  <div
                    key={idx}
                    className="p-2.5 rounded-lg bg-[#1B191E] border border-[#2E2A32] text-[#E8B968]"
                  >
                    <span className="font-semibold">Question: </span>
                    {typeof q === "string" ? q : (q.question as string) || JSON.stringify(q)}
                  </div>
                ))}
                {assumptions.map((a, idx) => (
                  <div
                    key={idx}
                    className="p-2.5 rounded-lg bg-[#1B191E] border border-[#2E2A32] text-[#B7AFBA]"
                  >
                    <span className="font-semibold text-[#77717C]">Assumption: </span>
                    {a}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Phase 6 Handoff Readiness Box */}
        <div className="p-6 rounded-2xl bg-gradient-to-br from-[#1B191E] to-[#131215] border border-[#E8B968]/30 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-[#F5CC7A] flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-[#E8B968]" />
              Phase 6 Handoff Status: Controlled Standby
            </h3>
            <span className="text-xs px-2.5 py-0.5 rounded-full bg-[#E8B968]/20 text-[#F5CC7A] border border-[#E8B968]/40">
              Awaiting Phase 6
            </span>
          </div>
          <p className="text-xs text-[#B7AFBA] leading-relaxed">
            This project has completed Gate 4 owner review and is safely locked as an official agency project record.
            No automated website generation, GitHub repository creation, or Vercel deployment will take place until Phase 6 is explicitly initiated.
          </p>
        </div>
      </div>
    </div>
  );
}
