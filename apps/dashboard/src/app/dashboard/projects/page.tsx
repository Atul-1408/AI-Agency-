"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import Link from "next/link";
import {
  api,
  type Project,
  type ProjectStatus,
} from "@/lib/api";
import {
  FolderKanban,
  Search,
  CheckCircle2,
  Clock,
  Sparkles,
  ChevronRight,
  ExternalLink,
  Layers,
  ArrowUpRight,
  FileText,
  AlertCircle,
  Building2,
} from "lucide-react";

function ProjectsContent() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [total, setTotal] = useState(0);
  const [readyCount, setReadyCount] = useState(0);
  const [inBuildCount, setInBuildCount] = useState(0);
  const [completedCount, setCompletedCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const fetchProjects = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.projects.list({
        status: statusFilter === "all" ? undefined : statusFilter,
        search: searchQuery || undefined,
      });
      setProjects(res.items || []);
      setTotal(res.total || 0);
      setReadyCount(res.ready_for_build_count || 0);
      setInBuildCount(res.in_build_count || 0);
      setCompletedCount(res.completed_count || 0);
    } catch (err) {
      console.error("Failed to load projects", err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, searchQuery]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const getStatusBadge = (status: ProjectStatus) => {
    switch (status) {
      case "ready_for_build":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[12px] font-medium bg-[#39C98A]/15 text-[#39C98A] border border-[#39C98A]/30">
            <span className="w-1.5 h-1.5 rounded-full bg-[#39C98A]" />
            Ready for Build
          </span>
        );
      case "in_build":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[12px] font-medium bg-[#E8B968]/15 text-[#E8B968] border border-[#E8B968]/30">
            <span className="w-1.5 h-1.5 rounded-full bg-[#E8B968] animate-pulse" />
            In Build
          </span>
        );
      case "completed":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[12px] font-medium bg-purple-500/15 text-purple-400 border border-purple-500/30">
            Completed
          </span>
        );
      case "cancelled":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[12px] font-medium bg-red-500/15 text-red-400 border border-red-500/30">
            Cancelled
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[12px] font-medium bg-white/10 text-white/70 border border-white/20">
            {status}
          </span>
        );
    }
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#E8B968]/20 to-[#A87932]/10 border border-[#E8B968]/30 flex items-center justify-center">
              <FolderKanban className="w-5 h-5 text-[#E8B968]" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-[#F5F1EA]">
                Client Projects
              </h1>
              <p className="text-sm text-[#77717C]">
                Official project records created from Gate 4 approved PRDs
              </p>
            </div>
          </div>
        </div>

        {/* Phase 6 readiness banner */}
        <div className="flex items-center gap-2.5 px-4 py-2 rounded-xl bg-[#171519] border border-[#242126] text-xs text-[#B7AFBA]">
          <span className="w-2 h-2 rounded-full bg-[#39C98A]" />
          <span>Handoff Foundation</span>
          <span className="text-[#77717C]">|</span>
          <span className="text-[#E8B968] font-medium">Phase 6 Ready</span>
        </div>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-5 rounded-2xl bg-[#131215] border border-[#242126] hover:border-[#38333D] transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#77717C]">Total Projects</span>
            <Layers className="w-4 h-4 text-[#77717C]" />
          </div>
          <p className="text-3xl font-bold text-[#F5F1EA] mt-2">{total}</p>
          <p className="text-xs text-[#77717C] mt-1">Controlled agency deliverables</p>
        </div>

        <div className="p-5 rounded-2xl bg-[#131215] border border-[#242126] hover:border-[#38333D] transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#77717C]">Ready for Build</span>
            <CheckCircle2 className="w-4 h-4 text-[#39C98A]" />
          </div>
          <p className="text-3xl font-bold text-[#39C98A] mt-2">{readyCount}</p>
          <p className="text-xs text-[#77717C] mt-1">Awaiting Phase 6 handoff</p>
        </div>

        <div className="p-5 rounded-2xl bg-[#131215] border border-[#242126] hover:border-[#38333D] transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#77717C]">In Build</span>
            <Clock className="w-4 h-4 text-[#E8B968]" />
          </div>
          <p className="text-3xl font-bold text-[#E8B968] mt-2">{inBuildCount}</p>
          <p className="text-xs text-[#77717C] mt-1">Phase 6 generation active</p>
        </div>

        <div className="p-5 rounded-2xl bg-[#131215] border border-[#242126] hover:border-[#38333D] transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#77717C]">Completed</span>
            <Sparkles className="w-4 h-4 text-purple-400" />
          </div>
          <p className="text-3xl font-bold text-purple-400 mt-2">{completedCount}</p>
          <p className="text-xs text-[#77717C] mt-1">Successfully delivered</p>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 p-4 rounded-2xl bg-[#131215] border border-[#242126]">
        <div className="relative w-full sm:w-80">
          <Search className="w-4 h-4 text-[#77717C] absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search projects or slug..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 rounded-xl bg-[#1B191E] border border-[#2E2A32] text-sm text-[#F5F1EA] placeholder-[#77717C] focus:outline-none focus:border-[#E8B968] transition-colors"
          />
        </div>

        <div className="flex items-center gap-2 overflow-x-auto w-full sm:w-auto">
          {[
            { id: "all", label: "All Statuses" },
            { id: "ready_for_build", label: "Ready for Build" },
            { id: "in_build", label: "In Build" },
            { id: "completed", label: "Completed" },
            { id: "cancelled", label: "Cancelled" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setStatusFilter(tab.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
                statusFilter === tab.id
                  ? "bg-[#E8B968]/20 text-[#F5CC7A] border border-[#E8B968]/40"
                  : "text-[#B7AFBA] hover:bg-[#1B191E] border border-transparent"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Projects List */}
      {loading ? (
        <div className="p-12 text-center text-[#77717C] rounded-2xl bg-[#131215] border border-[#242126]">
          <div className="w-6 h-6 border-2 border-[#E8B968] border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-sm">Loading agency projects...</p>
        </div>
      ) : projects.length === 0 ? (
        <div className="p-12 text-center rounded-2xl bg-[#131215] border border-[#242126]">
          <div className="w-12 h-12 rounded-2xl bg-[#1B191E] border border-[#242126] flex items-center justify-center mx-auto mb-4">
            <FolderKanban className="w-6 h-6 text-[#77717C]" />
          </div>
          <h3 className="text-base font-semibold text-[#F5F1EA]">No projects found</h3>
          <p className="text-sm text-[#77717C] mt-1 max-w-md mx-auto">
            {searchQuery || statusFilter !== "all"
              ? "No projects match your search or filter criteria."
              : "Projects are created under human control from Gate 4 APPROVED PRDs."}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {projects.map((p) => {
            const bizName = (p.phase_metadata?.business_name as string) || "Client Business";
            const bizDomain = (p.phase_metadata?.business_domain as string) || "";
            const openQuestions = (p.phase_metadata?.open_questions as unknown[]) || [];
            const traceability = (p.phase_metadata?.requirement_traceability as Record<string, unknown>) || {};
            const createdDate = new Date(p.created_at).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
              year: "numeric",
            });
            const updatedDate = new Date(p.updated_at).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
              year: "numeric",
            });

            return (
              <Link
                key={p.id}
                href={`/dashboard/projects/${p.id}`}
                className="group p-5 rounded-2xl bg-[#131215] border border-[#242126] hover:border-[#E8B968]/40 hover:bg-[#161418] transition-all flex flex-col md:flex-row md:items-center justify-between gap-4"
              >
                <div className="space-y-2 flex-1">
                  <div className="flex flex-wrap items-center gap-3">
                    <h3 className="text-base font-semibold text-[#F5F1EA] group-hover:text-[#F5CC7A] transition-colors">
                      {p.project_name}
                    </h3>
                    {getStatusBadge(p.project_status)}
                    <span className="text-xs font-mono px-2 py-0.5 rounded bg-[#1B191E] border border-[#242126] text-[#77717C]">
                      PRD v{p.prd_version}
                    </span>
                  </div>

                  <div className="flex flex-wrap items-center gap-4 text-xs text-[#77717C]">
                    <div className="flex items-center gap-1.5 text-[#B7AFBA]">
                      <Building2 className="w-3.5 h-3.5 text-[#77717C]" />
                      <span>{bizName}</span>
                      {bizDomain && <span className="text-[#77717C]">({bizDomain})</span>}
                    </div>
                    <span>•</span>
                    <span>Slug: <span className="font-mono text-[#F5F1EA]/80">{p.project_slug}</span></span>
                    <span>•</span>
                    <span>Traceability: <span className="text-[#39C98A] font-medium">{Object.keys(traceability).length} reqs</span></span>
                    {openQuestions.length > 0 && (
                      <>
                        <span>•</span>
                        <span className="text-[#E8B968] flex items-center gap-1">
                          <AlertCircle className="w-3 h-3" />
                          {openQuestions.length} open questions
                        </span>
                      </>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-6 self-end md:self-center">
                  <div className="text-right text-xs">
                    <p className="text-[#77717C]">Created</p>
                    <p className="text-[#B7AFBA] font-medium mt-0.5">{createdDate}</p>
                    <p className="text-[10px] text-[#77717C] mt-0.5">Updated: {updatedDate}</p>
                  </div>

                  <div className="w-9 h-9 rounded-xl bg-[#1B191E] border border-[#242126] flex items-center justify-center group-hover:border-[#E8B968]/40 group-hover:bg-[#E8B968]/10 transition-colors">
                    <ChevronRight className="w-4 h-4 text-[#77717C] group-hover:text-[#F5CC7A] transition-colors" />
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function ProjectsPage() {
  return (
    <Suspense
      fallback={
        <div className="p-8 text-center text-[#77717C]">
          Loading Projects Dashboard...
        </div>
      }
    >
      <ProjectsContent />
    </Suspense>
  );
}
