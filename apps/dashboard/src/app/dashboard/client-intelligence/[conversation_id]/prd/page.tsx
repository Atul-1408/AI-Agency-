"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ShieldAlert,
  CheckCircle,
  XCircle,
  Clock,
  ArrowLeft,
  FileText,
  AlertTriangle,
  RefreshCw,
  ExternalLink,
  Layers,
  HelpCircle,
  FolderKanban,
  Sparkles,
} from "lucide-react";
import { api, PRDDetail, PRDStatus } from "@/lib/api";

export default function PRDReviewPage() {
  const params = useParams();
  const router = useRouter();
  const conversationId = params?.conversation_id as string;

  const [prd, setPrd] = useState<PRDDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [rejectionModalOpen, setRejectionModalOpen] = useState<boolean>(false);
  const [rejectionReason, setRejectionReason] = useState<string>("");
  const [createProjectModalOpen, setCreateProjectModalOpen] = useState<boolean>(false);
  const [existingProjectId, setExistingProjectId] = useState<string | null>(null);

  const loadPRD = useCallback(async () => {
    if (!conversationId) return;
    setLoading(true);
    setError(null);
    try {
      // Find PRDs for this conversation
      const prds = await api.prd.list(conversationId);
      if (prds && prds.length > 0) {
        // Fetch detailed record of latest PRD
        const detail = await api.prd.get(prds[0].id);
        setPrd(detail);
      } else {
        // Automatically attempt to generate PRD draft if none exists yet
        const generated = await api.prd.generate(conversationId);
        setPrd(generated);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load PRD";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    loadPRD();
  }, [loadPRD]);

  const handleApprove = async () => {
    if (!prd) return;
    setActionLoading("approve");
    try {
      const updated = await api.prd.approve(prd.id);
      setPrd((prev) => (prev ? { ...prev, status: updated.status, approved_at: updated.approved_at, approved_by: updated.approved_by } : null));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to approve PRD");
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async () => {
    if (!prd) return;
    setActionLoading("reject");
    try {
      const updated = await api.prd.reject(prd.id, rejectionReason || undefined);
      setPrd((prev) => (prev ? { ...prev, status: updated.status, rejected_at: updated.rejected_at, rejected_by: updated.rejected_by, rejection_reason: updated.rejection_reason } : null));
      setRejectionModalOpen(false);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to reject PRD");
    } finally {
      setActionLoading(null);
    }
  };

  useEffect(() => {
    if (!prd || prd.status !== "approved") return;
    api.projects
      .list()
      .then((res) => {
        const match = res.items.find((p) => p.approved_prd_id === prd.id);
        if (match) setExistingProjectId(match.id);
      })
      .catch(() => {});
  }, [prd]);

  const handleCreateProject = async () => {
    if (!prd) return;
    setActionLoading("create_project");
    try {
      const proj = await api.projects.create({ approved_prd_id: prd.id });
      setCreateProjectModalOpen(false);
      router.push(`/dashboard/projects/${proj.id}`);
    } catch (err: unknown) {
      const maybeErr = err as { detail?: { existing_project_id?: string } };
      if (maybeErr?.detail?.existing_project_id) {
        setCreateProjectModalOpen(false);
        router.push(`/dashboard/projects/${maybeErr.detail.existing_project_id}`);
      } else {
        alert(err instanceof Error ? err.message : "Failed to create project");
      }
    } finally {
      setActionLoading(null);
    }
  };

  const handleRegenerate = async () => {
    if (!conversationId) return;
    setActionLoading("generate");
    try {
      const generated = await api.prd.generate(conversationId);
      setPrd(generated);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to regenerate PRD");
    } finally {
      setActionLoading(null);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-4">
        <RefreshCw className="w-8 h-8 text-[#E8B968] animate-spin" />
        <p className="text-[14px] text-[#B7AFBA]">Loading Product Requirement Document...</p>
      </div>
    );
  }

  if (error || !prd) {
    return (
      <div className="p-8 max-w-4xl mx-auto space-y-6">
        <button
          onClick={() => router.back()}
          className="flex items-center space-x-2 text-[13px] text-[#A29A98] hover:text-[#F5F1EA] transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back</span>
        </button>
        <div className="bg-[#1C1A1E] border border-[#3E3835] rounded-xl p-8 text-center space-y-4">
          <AlertTriangle className="w-10 h-10 text-[#E8B968] mx-auto" />
          <h2 className="text-[20px] font-medium text-[#F5F1EA]">PRD Unavailable</h2>
          <p className="text-[14px] text-[#A29A98] max-w-md mx-auto">
            {error || "No PRD could be loaded for this conversation. Ensure requirements have been extracted first."}
          </p>
          <button
            onClick={handleRegenerate}
            disabled={actionLoading === "generate"}
            className="px-4 py-2 bg-[#E8B968] text-[#141216] text-[13px] font-medium rounded-lg hover:bg-[#F0C980] transition-colors"
          >
            {actionLoading === "generate" ? "Generating..." : "Generate PRD Draft"}
          </button>
        </div>
      </div>
    );
  }

  const getStatusBadge = (status: PRDStatus) => {
    switch (status) {
      case "approved":
        return (
          <span className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full text-[12px] font-semibold bg-[#1C3325] text-[#4ADE80] border border-[#235334]">
            <CheckCircle className="w-3.5 h-3.5" />
            <span>APPROVED (Gate 4 Complete)</span>
          </span>
        );
      case "rejected":
        return (
          <span className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full text-[12px] font-semibold bg-[#36181B] text-[#F87171] border border-[#5A2429]">
            <XCircle className="w-3.5 h-3.5" />
            <span>REJECTED</span>
          </span>
        );
      case "superseded":
        return (
          <span className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full text-[12px] font-semibold bg-[#262329] text-[#9E95A2] border border-[#3D3842]">
            <span>SUPERSEDED</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full text-[12px] font-semibold bg-[#3A2D1B] text-[#FBBF24] border border-[#5C4724]">
            <Clock className="w-3.5 h-3.5" />
            <span>PENDING APPROVAL (Gate 4)</span>
          </span>
        );
    }
  };

  return (
    <div className="pb-16 max-w-6xl mx-auto space-y-8 animate-fade-in">
      {/* Top Breadcrumb & Navigation */}
      <div className="flex items-center justify-between border-b border-[#242126] pb-4">
        <button
          onClick={() => router.back()}
          className="flex items-center space-x-2 text-[13px] text-[#A29A98] hover:text-[#F5F1EA] transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to Conversation</span>
        </button>
        <div className="flex items-center space-x-3">
          {prd.status !== "approved" && (
            <button
              onClick={handleRegenerate}
              disabled={!!actionLoading}
              className="px-3 py-1.5 bg-[#232025] hover:bg-[#2D2A30] text-[#D8D2DC] text-[12px] font-medium rounded-lg border border-[#353039] transition-colors flex items-center space-x-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${actionLoading === "generate" ? "animate-spin" : ""}`} />
              <span>Regenerate Draft (v{prd.version + 1})</span>
            </button>
          )}
        </div>
      </div>

      {/* Gate 4 Banner */}
      <div className="bg-[#1C1A1E] border border-[#302B34] rounded-xl p-6 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center space-x-3 mb-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-[#E8B968]">
                Gate 4 Owner Review
              </span>
              <span className="text-[#5D5564]">•</span>
              <span className="text-[12px] text-[#A29A98]">Version {prd.version}</span>
              {getStatusBadge(prd.status)}
            </div>
            <h1 className="font-display text-[28px] md:text-[32px] font-normal text-[#F5F1EA] tracking-tight">
              {prd.title}
            </h1>
            <p className="text-[13px] text-[#A29A98] mt-1">
              Generated on {new Date(prd.generated_at).toLocaleString()} • Owner: {prd.owner_email}
            </p>
          </div>

          {/* Gate 4 Action Controls */}
          {prd.status === "pending_approval" && (
            <div className="flex items-center space-x-3">
              <button
                onClick={() => setRejectionModalOpen(true)}
                disabled={!!actionLoading}
                className="px-4 py-2.5 bg-[#36181B] hover:bg-[#4A2024] text-[#F87171] border border-[#5A2429] text-[13px] font-medium rounded-lg transition-colors flex items-center space-x-2"
              >
                <XCircle className="w-4 h-4" />
                <span>REJECT PRD</span>
              </button>
              <button
                onClick={handleApprove}
                disabled={!!actionLoading}
                className="px-5 py-2.5 bg-[#1C3325] hover:bg-[#244531] text-[#4ADE80] border border-[#2B603D] text-[13px] font-semibold rounded-lg transition-colors flex items-center space-x-2 shadow-sm"
              >
                <CheckCircle className="w-4 h-4" />
                <span>{actionLoading === "approve" ? "Approving..." : "APPROVE PRD (GATE 4)"}</span>
              </button>
            </div>
          )}

          {prd.status === "approved" && (
            <div className="flex flex-col sm:flex-row items-end sm:items-center gap-3">
              <div className="p-3 bg-[#16271D] border border-[#235334] rounded-lg text-right">
                <p className="text-[12px] font-semibold text-[#4ADE80]">Approved & Immutable</p>
                <p className="text-[11px] text-[#86EFAC] mt-0.5">
                  Approved by {prd.approved_by} on {prd.approved_at ? new Date(prd.approved_at).toLocaleString() : ""}
                </p>
              </div>

              {existingProjectId ? (
                <button
                  onClick={() => router.push(`/dashboard/projects/${existingProjectId}`)}
                  className="px-4 py-2.5 bg-[#1B191E] hover:bg-[#25222A] text-[#F5CC7A] border border-[#E8B968]/40 text-[13px] font-semibold rounded-lg transition-colors flex items-center space-x-2 shadow-sm"
                >
                  <FolderKanban className="w-4 h-4 text-[#E8B968]" />
                  <span>VIEW PROJECT</span>
                </button>
              ) : (
                <button
                  onClick={() => setCreateProjectModalOpen(true)}
                  disabled={!!actionLoading}
                  className="px-5 py-2.5 bg-[#E8B968] hover:bg-[#F5CC7A] text-[#141216] text-[13px] font-bold rounded-lg transition-colors flex items-center space-x-2 shadow-sm"
                >
                  <Sparkles className="w-4 h-4 text-[#141216]" />
                  <span>CREATE PROJECT</span>
                </button>
              )}
            </div>
          )}

          {prd.status === "rejected" && (
            <div className="p-3 bg-[#2D1619] border border-[#5A2429] rounded-lg text-right">
              <p className="text-[12px] font-semibold text-[#F87171]">Rejected by Owner</p>
              {prd.rejection_reason && (
                <p className="text-[11px] text-[#FCA5A5] mt-0.5 max-w-xs">{prd.rejection_reason}</p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Completeness & Metrics Overview */}
      {prd.completeness && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-[#18161A] border border-[#2B2730] p-4 rounded-xl">
            <span className="text-[11px] font-medium text-[#8F8795] uppercase">Total Completeness</span>
            <div className="flex items-baseline space-x-2 mt-1">
              <span className="text-[28px] font-semibold text-[#F5F1EA]">
                {prd.completeness.overall_completeness_percentage}%
              </span>
              <span className="text-[12px] text-[#8F8795]">
                ({prd.completeness.total_present}/{prd.completeness.total_fields} fields)
              </span>
            </div>
            <div className="w-full bg-[#262329] h-1.5 rounded-full mt-3 overflow-hidden">
              <div
                className="bg-[#E8B968] h-full rounded-full"
                style={{ width: `${prd.completeness.overall_completeness_percentage}%` }}
              />
            </div>
          </div>

          <div className="bg-[#18161A] border border-[#2B2730] p-4 rounded-xl">
            <span className="text-[11px] font-medium text-[#8F8795] uppercase">Authoritative Traceability</span>
            <div className="text-[28px] font-semibold text-[#F5F1EA] mt-1">
              {prd.requirement_references?.length || Object.keys(prd.requirement_traceability || {}).length}
            </div>
            <p className="text-[11px] text-[#8F8795] mt-1">Traced to client messages & evidence</p>
          </div>

          <div className="bg-[#18161A] border border-[#2B2730] p-4 rounded-xl">
            <span className="text-[11px] font-medium text-[#8F8795] uppercase">Open Questions</span>
            <div className="text-[28px] font-semibold text-[#E8B968] mt-1">
              {prd.open_questions?.length || 0}
            </div>
            <p className="text-[11px] text-[#8F8795] mt-1">Unresolved fields / clarifications</p>
          </div>

          <div className="bg-[#18161A] border border-[#2B2730] p-4 rounded-xl">
            <span className="text-[11px] font-medium text-[#8F8795] uppercase">Immutability Lock</span>
            <div className="text-[16px] font-semibold text-[#F5F1EA] mt-2 flex items-center space-x-2">
              <ShieldAlert className="w-4 h-4 text-[#E8B968]" />
              <span>{prd.status === "approved" ? "Enforced" : "Unlocked (Pending)"}</span>
            </div>
            <p className="text-[11px] text-[#8F8795] mt-1">Owner-only Gate 4 control</p>
          </div>
        </div>
      )}

      {/* Main PRD Content Grid */}
      <div className="space-y-6">
        {/* 1. Executive Summary */}
        <section className="bg-[#18161A] border border-[#2B2730] rounded-xl p-6 space-y-3">
          <h2 className="text-[16px] font-semibold text-[#F5F1EA] flex items-center space-x-2">
            <FileText className="w-4 h-4 text-[#E8B968]" />
            <span>1. Executive Summary</span>
          </h2>
          <p className="text-[14px] text-[#D8D2DC] leading-relaxed whitespace-pre-line">
            {prd.executive_summary}
          </p>
        </section>

        {/* 2. Business Information & Goals */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <section className="bg-[#18161A] border border-[#2B2730] rounded-xl p-6 space-y-4">
            <h2 className="text-[16px] font-semibold text-[#F5F1EA]">2. Business Information</h2>
            <dl className="grid grid-cols-2 gap-y-3 text-[13px]">
              <dt className="text-[#8F8795]">Business Name:</dt>
              <dd className="text-[#F5F1EA] font-medium">{String(prd.business_overview?.business_name ?? "UNKNOWN")}</dd>
              <dt className="text-[#8F8795]">Business Type:</dt>
              <dd className="text-[#F5F1EA]">{String(prd.business_overview?.business_type ?? "UNKNOWN")}</dd>
              <dt className="text-[#8F8795]">Industry:</dt>
              <dd className="text-[#F5F1EA]">{String(prd.business_overview?.industry ?? "NOT_SPECIFIED")}</dd>
              <dt className="text-[#8F8795]">Services:</dt>
              <dd className="text-[#F5F1EA]">{String(prd.business_overview?.services ?? "NOT_SPECIFIED")}</dd>
              <dt className="text-[#8F8795]">Website Type:</dt>
              <dd className="text-[#F5F1EA]">{String(prd.business_overview?.website_type ?? "NOT_SPECIFIED")}</dd>
            </dl>
          </section>

          <section className="bg-[#18161A] border border-[#2B2730] rounded-xl p-6 space-y-4">
            <h2 className="text-[16px] font-semibold text-[#F5F1EA]">3. Business Goals & Audience</h2>
            <div className="space-y-3">
              <div>
                <h3 className="text-[12px] font-semibold uppercase text-[#8F8795] mb-1">Target Audience</h3>
                <p className="text-[13px] text-[#F5F1EA]">{String(prd.target_audience ?? "UNKNOWN")}</p>
              </div>
              <div>
                <h3 className="text-[12px] font-semibold uppercase text-[#8F8795] mb-1">Primary Goals</h3>
                <ul className="list-disc list-inside text-[13px] text-[#F5F1EA] space-y-1">
                  {prd.goals?.map((g, idx) => (
                    <li key={idx}>{g}</li>
                  ))}
                </ul>
              </div>
            </div>
          </section>
        </div>

        {/* 3. Sitemap & Page Requirements */}
        <section className="bg-[#18161A] border border-[#2B2730] rounded-xl p-6 space-y-4">
          <h2 className="text-[16px] font-semibold text-[#F5F1EA] flex items-center space-x-2">
            <Layers className="w-4 h-4 text-[#E8B968]" />
            <span>4. Sitemap & Page Structure</span>
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            {prd.sitemap?.map((item, idx) => (
              <div key={idx} className="p-3 bg-[#201D23] border border-[#302B35] rounded-lg">
                <span className="text-[13px] font-medium text-[#F5F1EA]">{item.page}</span>
                <span className="block text-[11px] text-[#8F8795] mt-0.5">Status: {item.status || "CONFIRMED"}</span>
              </div>
            ))}
          </div>
        </section>

        {/* 4. Functionality, Design & Technical */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <section className="bg-[#18161A] border border-[#2B2730] rounded-xl p-6 space-y-3">
            <h2 className="text-[15px] font-semibold text-[#F5F1EA]">5. Functionality</h2>
            <dl className="space-y-2 text-[13px]">
              <div>
                <dt className="text-[#8F8795] text-[11px] uppercase">Features</dt>
                <dd className="text-[#F5F1EA] mt-0.5">{String(prd.functionality_requirements?.features ?? "NOT_SPECIFIED")}</dd>
              </div>
              <div>
                <dt className="text-[#8F8795] text-[11px] uppercase">Integrations</dt>
                <dd className="text-[#F5F1EA] mt-0.5">{String(prd.functionality_requirements?.integrations ?? "NOT_SPECIFIED")}</dd>
              </div>
              <div>
                <dt className="text-[#8F8795] text-[11px] uppercase">Booking / Payments</dt>
                <dd className="text-[#F5F1EA] mt-0.5">{String(prd.functionality_requirements?.booking_requirements ?? "NOT_SPECIFIED")}</dd>
              </div>
            </dl>
          </section>

          <section className="bg-[#18161A] border border-[#2B2730] rounded-xl p-6 space-y-3">
            <h2 className="text-[15px] font-semibold text-[#F5F1EA]">6. Design & Branding</h2>
            <dl className="space-y-2 text-[13px]">
              <div>
                <dt className="text-[#8F8795] text-[11px] uppercase">Design Preferences</dt>
                <dd className="text-[#F5F1EA] mt-0.5">{String(prd.design_requirements?.design_preferences ?? "NOT_SPECIFIED")}</dd>
              </div>
              <div>
                <dt className="text-[#8F8795] text-[11px] uppercase">Brand Colors</dt>
                <dd className="text-[#F5F1EA] mt-0.5">{String(prd.branding_requirements?.colors ?? "NOT_SPECIFIED")}</dd>
              </div>
              <div>
                <dt className="text-[#8F8795] text-[11px] uppercase">Typography</dt>
                <dd className="text-[#F5F1EA] mt-0.5">{String(prd.branding_requirements?.typography ?? "NOT_SPECIFIED")}</dd>
              </div>
            </dl>
          </section>

          <section className="bg-[#18161A] border border-[#2B2730] rounded-xl p-6 space-y-3">
            <h2 className="text-[15px] font-semibold text-[#F5F1EA]">7. Technical & Timeline</h2>
            <dl className="space-y-2 text-[13px]">
              <div>
                <dt className="text-[#8F8795] text-[11px] uppercase">Technical Details</dt>
                <dd className="text-[#F5F1EA] mt-0.5">{String(prd.technical_requirements?.technical_details ?? "NOT_SPECIFIED")}</dd>
              </div>
              <div>
                <dt className="text-[#8F8795] text-[11px] uppercase">Timeline / Urgency</dt>
                <dd className="text-[#F5F1EA] mt-0.5">{String(prd.timeline?.timeline_details ?? "NOT_SPECIFIED")}</dd>
              </div>
              <div>
                <dt className="text-[#8F8795] text-[11px] uppercase">Budget</dt>
                <dd className="text-[#F5F1EA] mt-0.5">{String(prd.budget?.budget_details ?? "NOT_SPECIFIED")}</dd>
              </div>
            </dl>
          </section>
        </div>

        {/* 5. Open Questions & Assumptions */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <section className="bg-[#18161A] border border-[#2B2730] rounded-xl p-6 space-y-4">
            <h2 className="text-[16px] font-semibold text-[#F5F1EA] flex items-center space-x-2">
              <HelpCircle className="w-4 h-4 text-[#E8B968]" />
              <span>8. Open Questions ({prd.open_questions?.length || 0})</span>
            </h2>
            <div className="space-y-3 max-h-80 overflow-y-auto pr-1">
              {prd.open_questions && prd.open_questions.length > 0 ? (
                prd.open_questions.map((q, idx) => (
                  <div key={idx} className="p-3 bg-[#201D23] border border-[#302B35] rounded-lg space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-semibold text-[#E8B968] uppercase">{String(q.category || "GENERAL")}</span>
                      <span className="text-[10px] bg-[#3A2D1B] text-[#FBBF24] px-1.5 py-0.5 rounded">OPEN</span>
                    </div>
                    <p className="text-[13px] text-[#F5F1EA] font-medium">{String(q.question)}</p>
                    {Boolean(q.rationale) ? <p className="text-[11px] text-[#8F8795]">{String(q.rationale)}</p> : null}
                  </div>
                ))
              ) : (
                <p className="text-[13px] text-[#8F8795]">No open questions identified.</p>
              )}
            </div>
          </section>

          <section className="bg-[#18161A] border border-[#2B2730] rounded-xl p-6 space-y-4">
            <h2 className="text-[16px] font-semibold text-[#F5F1EA]">9. Explicit Assumptions</h2>
            <ul className="space-y-2 text-[13px] text-[#D8D2DC]">
              {prd.assumptions?.map((a, idx) => (
                <li key={idx} className="p-3 bg-[#201D23] border border-[#302B35] rounded-lg flex items-start space-x-2">
                  <span className="text-[#E8B968]">•</span>
                  <span>{a}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>

        {/* 6. Requirement Traceability & Evidence Records */}
        <section className="bg-[#18161A] border border-[#2B2730] rounded-xl p-6 space-y-4">
          <h2 className="text-[16px] font-semibold text-[#F5F1EA]">10. Requirement Traceability Matrix</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[12px]">
              <thead className="bg-[#201D23] text-[#8F8795] uppercase font-semibold border-b border-[#302B35]">
                <tr>
                  <th className="p-3">Section / Key</th>
                  <th className="p-3">Req Version</th>
                  <th className="p-3">Evidence Excerpt</th>
                  <th className="p-3">Verified Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#2B2730]">
                {prd.requirement_references && prd.requirement_references.length > 0 ? (
                  prd.requirement_references.map((ref) => (
                    <tr key={ref.id} className="hover:bg-[#201D23]/50">
                      <td className="p-3 font-medium text-[#F5F1EA]">{ref.section_key}</td>
                      <td className="p-3 text-[#E8B968]">v{ref.requirement_version}</td>
                      <td className="p-3 text-[#D8D2DC] max-w-md truncate" title={ref.evidence_excerpt || ""}>
                        {ref.evidence_excerpt || "Verified from client conversation"}
                      </td>
                      <td className="p-3 text-[#8F8795]">
                        {new Date(ref.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={4} className="p-4 text-center text-[#8F8795]">
                      No references found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* Rejection Modal */}
      {rejectionModalOpen && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="bg-[#1C1A1E] border border-[#3E3835] rounded-xl p-6 max-w-md w-full space-y-4">
            <h3 className="text-[18px] font-semibold text-[#F5F1EA]">Reject PRD Draft (Gate 4)</h3>
            <p className="text-[13px] text-[#A29A98]">
              Please state why this PRD is being rejected. This feedback will be audited and preserved for future revisions.
            </p>
            <textarea
              value={rejectionReason}
              onChange={(e) => setRejectionReason(e.target.value)}
              placeholder="e.g., Client requested e-commerce shop, but PRD lacks payment gateway requirements."
              className="w-full bg-[#141216] border border-[#302B35] rounded-lg p-3 text-[13px] text-[#F5F1EA] placeholder-[#5D5564] focus:outline-none focus:border-[#E8B968] resize-none h-24"
            />
            <div className="flex items-center justify-end space-x-3 pt-2">
              <button
                onClick={() => setRejectionModalOpen(false)}
                className="px-4 py-2 text-[13px] text-[#A29A98] hover:text-[#F5F1EA] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={actionLoading === "reject"}
                className="px-4 py-2 bg-[#36181B] hover:bg-[#4A2024] text-[#F87171] border border-[#5A2429] text-[13px] font-semibold rounded-lg transition-colors"
              >
                {actionLoading === "reject" ? "Rejecting..." : "Confirm Rejection"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Project Confirmation Modal */}
      {createProjectModalOpen && prd && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="bg-[#1C1A1E] border border-[#3E3835] rounded-xl p-6 max-w-md w-full space-y-4 shadow-2xl">
            <div className="flex items-center space-x-3">
              <div className="w-10 h-10 rounded-xl bg-[#E8B968]/20 border border-[#E8B968]/30 flex items-center justify-center">
                <FolderKanban className="w-5 h-5 text-[#E8B968]" />
              </div>
              <div>
                <h3 className="text-[18px] font-semibold text-[#F5F1EA]">Create Official Project</h3>
                <p className="text-[12px] text-[#77717C]">Phase 5.4 Human-Controlled Gate</p>
              </div>
            </div>

            <div className="p-4 rounded-xl bg-[#141216] border border-[#2B2730] space-y-2">
              <p className="text-[13px] text-[#F5F1EA] leading-relaxed">
                You are creating a project from approved PRD v{prd.version}.
              </p>
              <p className="text-[12px] text-[#A29A98] leading-relaxed">
                This will create the official project handoff for Phase 6. No automated website generation or deployment will occur without your explicit command.
              </p>
            </div>

            <div className="flex items-center justify-end space-x-3 pt-2">
              <button
                onClick={() => setCreateProjectModalOpen(false)}
                disabled={actionLoading === "create_project"}
                className="px-4 py-2 text-[13px] text-[#A29A98] hover:text-[#F5F1EA] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateProject}
                disabled={actionLoading === "create_project"}
                className="px-5 py-2.5 bg-[#E8B968] hover:bg-[#F5CC7A] text-[#141216] text-[13px] font-bold rounded-lg transition-colors flex items-center space-x-2"
              >
                {actionLoading === "create_project" ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    <span>Creating...</span>
                  </>
                ) : (
                  <>
                    <CheckCircle className="w-4 h-4" />
                    <span>Confirm & Create Project</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
