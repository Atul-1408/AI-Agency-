"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import {
  Mail,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Edit3,
  RotateCw,
  Search,
  Filter,
  Clock,
  Sparkles,
  Info,
  Check,
  X,
  FileText,
  Building,
  ChevronRight,
  ExternalLink,
} from "lucide-react";
import { api, type OutreachDraft, type OutreachDraftStatus } from "@/lib/api";

type FilterTab = "all" | "pending_approval" | "approved" | "rejected";

function OutreachContent() {
  const searchParams = useSearchParams();
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const pageSize = 20;

  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Filters
  const [activeTab, setActiveTab] = useState<FilterTab>("all");
  const [searchEmail, setSearchEmail] = useState<string>("");

  // Modals & Panels
  const [selectedDraft, setSelectedDraft] = useState<OutreachDraft | null>(null);
  const [approveConfirmDraft, setApproveConfirmDraft] = useState<OutreachDraft | null>(null);
  const [rejectModalDraft, setRejectModalDraft] = useState<OutreachDraft | null>(null);
  const [rejectionReason, setRejectionReason] = useState<string>("");
  const [resetModalDraft, setResetModalDraft] = useState<OutreachDraft | null>(null);

  // Edit Mode inside review panel
  const [isEditing, setIsEditing] = useState<boolean>(false);
  const [editSubject, setEditSubject] = useState<string>("");
  const [editBody, setEditBody] = useState<string>("");

  // Auto-dismiss banners
  useEffect(() => {
    if (successMessage) {
      const timer = setTimeout(() => setSuccessMessage(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [successMessage]);

  const fetchDrafts = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const statusParam = activeTab === "all" ? undefined : activeTab;
      const res = await api.outreach.listDrafts({
        page,
        page_size: pageSize,
        status: statusParam,
        recipient_email: searchEmail ? searchEmail.trim() : undefined,
      });
      setDrafts(res.items || []);
      setTotalCount(res.total || 0);

      // If a draft is selected, keep its reference refreshed
      if (selectedDraft) {
        const found = res.items.find((d) => d.id === selectedDraft.id);
        if (found) setSelectedDraft(found);
      }
    } catch (err: unknown) {
      const errorObj = err as { detail?: string; status?: number };
      const msg = errorObj.detail || "Failed to load outreach drafts from server.";
      setErrorMessage(msg);
    } finally {
      setLoading(false);
    }
  }, [activeTab, searchEmail, page, selectedDraft]);

  // Initial load & filter change
  useEffect(() => {
    let mounted = true;
    setLoading(true);
    const statusParam = activeTab === "all" ? undefined : activeTab;
    api.outreach
      .listDrafts({
        page,
        page_size: pageSize,
        status: statusParam,
        recipient_email: searchEmail ? searchEmail.trim() : undefined,
      })
      .then((res) => {
        if (mounted) {
          setDrafts(res.items || []);
          setTotalCount(res.total || 0);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (mounted) {
          const errorObj = err as { detail?: string };
          setErrorMessage(errorObj.detail || "Unable to connect to API.");
          setLoading(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, [activeTab, searchEmail, page]);

  // Open single draft review
  const handleOpenReview = (draft: OutreachDraft) => {
    setSelectedDraft(draft);
    setIsEditing(false);
    setEditSubject(draft.subject);
    setEditBody(draft.body_text);
  };

  // Close review
  const handleCloseReview = () => {
    setSelectedDraft(null);
    setIsEditing(false);
  };

  // Approve Draft
  const handleApprove = async (draft: OutreachDraft) => {
    setActionLoading(`approve-${draft.id}`);
    setErrorMessage(null);
    try {
      const updated = await api.outreach.approveDraft(draft.id);
      setSuccessMessage(`Draft for ${draft.company_name || draft.recipient_email} approved for Gate 2!`);
      setApproveConfirmDraft(null);
      if (selectedDraft?.id === draft.id) setSelectedDraft(updated);
      await fetchDrafts();
    } catch (err: unknown) {
      const errorObj = err as { detail?: string };
      setErrorMessage(errorObj.detail || "Approval request failed.");
    } finally {
      setActionLoading(null);
    }
  };

  // Reject Draft
  const handleReject = async (draft: OutreachDraft) => {
    if (!rejectionReason.trim()) {
      setErrorMessage("Please enter a valid rejection reason.");
      return;
    }
    setActionLoading(`reject-${draft.id}`);
    setErrorMessage(null);
    try {
      const updated = await api.outreach.rejectDraft(draft.id, rejectionReason.trim());
      setSuccessMessage(`Draft for ${draft.company_name || draft.recipient_email} rejected.`);
      setRejectModalDraft(null);
      setRejectionReason("");
      if (selectedDraft?.id === draft.id) setSelectedDraft(updated);
      await fetchDrafts();
    } catch (err: unknown) {
      const errorObj = err as { detail?: string };
      setErrorMessage(errorObj.detail || "Rejection request failed.");
    } finally {
      setActionLoading(null);
    }
  };

  // Edit Draft
  const handleSaveEdit = async () => {
    if (!selectedDraft) return;
    if (!editSubject.trim() || !editBody.trim()) {
      setErrorMessage("Subject line and email body cannot be empty.");
      return;
    }
    setActionLoading(`edit-${selectedDraft.id}`);
    setErrorMessage(null);
    try {
      const updated = await api.outreach.editDraft(selectedDraft.id, {
        subject: editSubject.trim(),
        body_text: editBody.trim(),
      });
      setSelectedDraft(updated);
      setIsEditing(false);
      setSuccessMessage("Draft content updated successfully. It remains in PENDING_APPROVAL.");
      await fetchDrafts();
    } catch (err: unknown) {
      const errorObj = err as { detail?: string };
      setErrorMessage(errorObj.detail || "Failed to update draft content.");
    } finally {
      setActionLoading(null);
    }
  };

  // Reset Draft
  const handleReset = async (draft: OutreachDraft) => {
    setActionLoading(`reset-${draft.id}`);
    setErrorMessage(null);
    try {
      const updated = await api.outreach.resetDraft(draft.id);
      setSuccessMessage(`Draft reset to PENDING_APPROVAL. Fresh owner approval will be required.`);
      setResetModalDraft(null);
      if (selectedDraft?.id === draft.id) setSelectedDraft(updated);
      await fetchDrafts();
    } catch (err: unknown) {
      const errorObj = err as { detail?: string };
      setErrorMessage(errorObj.detail || "Failed to reset draft.");
    } finally {
      setActionLoading(null);
    }
  };

  // Helper status badge renderer
  const renderStatusBadge = (status: OutreachDraftStatus) => {
    switch (status) {
      case "pending_approval":
        return (
          <div className="flex flex-col items-start">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#E8B968]/15 border border-[#E8B968]/30 text-[#E8B968]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#E8B968] animate-pulse" />
              PENDING APPROVAL
            </span>
            <span className="text-[10px] text-[#A69EAA] mt-0.5 tracking-tight font-medium">
              Owner Review Required
            </span>
          </div>
        );
      case "approved":
        return (
          <div className="flex flex-col items-start">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#39C98A]/15 border border-[#39C98A]/30 text-[#39C98A]">
              <Check size={11} strokeWidth={3} />
              APPROVED
            </span>
            <span className="text-[10px] text-[#39C98A] mt-0.5 font-medium">
              Gate 2 Passed · Approved for Safety Validation
            </span>
          </div>
        );
      case "rejected":
        return (
          <div className="flex flex-col items-start">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#F87171]/15 border border-[#F87171]/30 text-[#F87171]">
              <X size={11} strokeWidth={3} />
              REJECTED
            </span>
            <span className="text-[10px] text-[#A69EAA] mt-0.5">Owner Rejected</span>
          </div>
        );
      default:
        return (
          <span className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-[#242126] text-[#B7AFBA]">
            {status.toUpperCase()}
          </span>
        );
    }
  };

  // Metrics counts
  const pendingCount = drafts.filter((d) => d.status === "pending_approval").length;
  const approvedCount = drafts.filter((d) => d.status === "approved").length;
  const rejectedCount = drafts.filter((d) => d.status === "rejected").length;

  return (
    <div className="pb-16 animate-fade-in text-[#F5F1EA]">
      {/* 1. Header Section */}
      <div className="mb-[32px] pb-4 border-b border-[#242126]">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[12px] font-semibold tracking-[0.16em] uppercase text-[#E8B968]">
                PHASE 3 — OUTREACH AGENT
              </span>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-[#E8B968]/15 border border-[#E8B968]/30 text-[#E8B968]">
                GATE 2 CONTROLLER
              </span>
            </div>
            <h1 className="font-display text-[38px] md:text-[46px] font-normal text-[#F5F1EA] leading-[1.08] tracking-tight">
              Outreach Console
            </h1>
            <p className="text-[15px] text-[#B7AFBA] mt-2 max-w-3xl leading-relaxed">
              Review and approve factual, personalized cold outreach emails generated for owner-qualified leads.
              Gate 2 human authorization is strictly mandatory before any downstream safety evaluation.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={fetchDrafts}
              disabled={loading}
              className="h-[40px] px-4 rounded-[10px] bg-[#171519] border border-[#302A30] hover:border-[#E8B968]/50 text-[13px] font-medium text-[#F5F1EA] flex items-center gap-2 transition-all"
            >
              <RotateCw size={15} className={loading ? "animate-spin text-[#E8B968]" : "text-[#B7AFBA]"} />
              <span>Refresh Queue</span>
            </button>
          </div>
        </div>
      </div>

      {/* Global Alerts */}
      {errorMessage && (
        <div className="mb-6 p-4 rounded-[12px] bg-[#F87171]/10 border border-[#F87171]/30 flex items-start justify-between gap-3 text-[#F87171]">
          <div className="flex items-start gap-3">
            <AlertCircle size={20} className="flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-[14px] font-semibold">Safety Alert / Request Error</p>
              <p className="text-[13px] opacity-90 mt-0.5">{errorMessage}</p>
            </div>
          </div>
          <button onClick={() => setErrorMessage(null)} className="text-[#F87171] hover:opacity-75">
            <X size={16} />
          </button>
        </div>
      )}

      {successMessage && (
        <div className="mb-6 p-4 rounded-[12px] bg-[#39C98A]/10 border border-[#39C98A]/30 flex items-start justify-between gap-3 text-[#39C98A]">
          <div className="flex items-start gap-3">
            <CheckCircle2 size={20} className="flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-[14px] font-semibold">Action Confirmed</p>
              <p className="text-[13px] opacity-90 mt-0.5">{successMessage}</p>
            </div>
          </div>
          <button onClick={() => setSuccessMessage(null)} className="text-[#39C98A] hover:opacity-75">
            <X size={16} />
          </button>
        </div>
      )}

      {/* 2. Safety Safeguard Banner */}
      <div className="p-[20px] rounded-[14px] bg-[#171519] border border-[#302A30] mb-[28px] flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-start gap-3.5">
          <div className="w-[42px] h-[42px] rounded-[10px] bg-[rgba(232,185,105,0.12)] flex items-center justify-center text-[#E8B968] flex-shrink-0 border border-[#E8B968]/20">
            <ShieldCheck size={22} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-[15px] font-semibold text-[#F5F1EA]">
                Gate 2 Approval Boundary
              </h3>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/30">
                SAFETY PROTOCOL
              </span>
            </div>
            <p className="text-[13px] text-[#B7AFBA] mt-1 leading-relaxed max-w-3xl">
              Approving a draft marks it as <strong className="text-[#F5F1EA]">Gate 2 Approved</strong>. It does not
              send an email. Approved drafts are forwarded to the Safety Controller to enforce strict rate limits
              (30 sends/day, 20 new leads/day, 120s pacing).
            </p>
          </div>
        </div>
      </div>

      {/* 3. Metrics Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-[28px]">
        <div className="p-4 rounded-[12px] bg-[#171519] border border-[#242126] flex items-center justify-between">
          <div>
            <p className="text-[12px] uppercase tracking-wider text-[#A69EAA] font-medium">Pending Review</p>
            <p className="text-[26px] font-bold text-[#E8B968] mt-1">{pendingCount}</p>
            <p className="text-[11px] text-[#A69EAA] mt-0.5">Owner review required</p>
          </div>
          <div className="w-10 h-10 rounded-[10px] bg-[#E8B968]/10 text-[#E8B968] flex items-center justify-center">
            <Clock size={20} />
          </div>
        </div>

        <div className="p-4 rounded-[12px] bg-[#171519] border border-[#242126] flex items-center justify-between">
          <div>
            <p className="text-[12px] uppercase tracking-wider text-[#A69EAA] font-medium">Approved (Gate 2)</p>
            <p className="text-[26px] font-bold text-[#39C98A] mt-1">{approvedCount}</p>
            <p className="text-[11px] text-[#39C98A] mt-0.5">Approved for Safety Validation</p>
          </div>
          <div className="w-10 h-10 rounded-[10px] bg-[#39C98A]/10 text-[#39C98A] flex items-center justify-center">
            <CheckCircle2 size={20} />
          </div>
        </div>

        <div className="p-4 rounded-[12px] bg-[#171519] border border-[#242126] flex items-center justify-between">
          <div>
            <p className="text-[12px] uppercase tracking-wider text-[#A69EAA] font-medium">Rejected</p>
            <p className="text-[26px] font-bold text-[#F87171] mt-1">{rejectedCount}</p>
            <p className="text-[11px] text-[#A69EAA] mt-0.5">Filtered from dispatch</p>
          </div>
          <div className="w-10 h-10 rounded-[10px] bg-[#F87171]/10 text-[#F87171] flex items-center justify-center">
            <XCircle size={20} />
          </div>
        </div>
      </div>

      {/* 4. Filter Toolbar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 mb-[20px] bg-[#171519] p-2.5 rounded-[12px] border border-[#242126]">
        {/* Status Tabs */}
        <div className="flex items-center gap-1 overflow-x-auto pb-1 sm:pb-0">
          {[
            { id: "all", label: "All Drafts" },
            { id: "pending_approval", label: "Pending Approval" },
            { id: "approved", label: "Approved" },
            { id: "rejected", label: "Rejected" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => {
                setActiveTab(tab.id as FilterTab);
                setPage(1);
              }}
              className={`px-3.5 py-1.5 rounded-[8px] text-[13px] font-medium transition-all ${
                activeTab === tab.id
                  ? "bg-[#E8B968] text-[#111013] font-semibold shadow-sm"
                  : "text-[#B7AFBA] hover:text-[#F5F1EA] hover:bg-[#242126]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Email Search */}
        <div className="relative min-w-[240px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#77717C]" />
          <input
            type="text"
            placeholder="Filter by recipient email..."
            value={searchEmail}
            onChange={(e) => {
              setSearchEmail(e.target.value);
              setPage(1);
            }}
            className="w-full h-[36px] pl-9 pr-3 rounded-[8px] bg-[#111013] border border-[#242126] text-[13px] text-[#F5F1EA] placeholder-[#77717C] focus:outline-none focus:border-[#E8B968]"
          />
          {searchEmail && (
            <button
              onClick={() => setSearchEmail("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#77717C] hover:text-[#F5F1EA]"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {/* 5. Draft Queue Table / List */}
      <div className="rounded-[14px] bg-[#171519] border border-[#242126] overflow-hidden">
        {loading ? (
          /* Skeleton Loader */
          <div className="p-8 space-y-4">
            {[1, 2, 3, 4].map((n) => (
              <div
                key={n}
                className="h-[68px] rounded-[10px] bg-[#111013]/60 animate-pulse border border-[#242126]"
              />
            ))}
          </div>
        ) : drafts.length === 0 ? (
          /* Authentic Empty State */
          <div className="p-16 text-center">
            <div className="w-16 h-16 rounded-full bg-[#111013] border border-[#302A30] text-[#77717C] flex items-center justify-center mx-auto mb-4">
              <Mail size={28} />
            </div>
            <h3 className="text-[17px] font-semibold text-[#F5F1EA]">
              {activeTab === "pending_approval"
                ? "No drafts awaiting approval"
                : "No outreach drafts found"}
            </h3>
            <p className="text-[14px] text-[#B7AFBA] max-w-md mx-auto mt-1 leading-relaxed">
              {activeTab === "pending_approval"
                ? "All qualified drafts have been reviewed or none are currently pending Gate 2 owner clearance."
                : "Generate personalized drafts by qualifying and approving leads in the Leads section."}
            </p>
          </div>
        ) : (
          <div>
            {/* Desktop Table View */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#242126] text-[11px] uppercase tracking-wider text-[#A69EAA] bg-[#111013]/40">
                    <th className="py-3 px-4 font-semibold">Company / Lead</th>
                    <th className="py-3 px-4 font-semibold">Recipient</th>
                    <th className="py-3 px-4 font-semibold">Subject</th>
                    <th className="py-3 px-4 font-semibold">Gate 2 Status</th>
                    <th className="py-3 px-4 font-semibold">Date</th>
                    <th className="py-3 px-4 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#242126]/60 text-[13px]">
                  {drafts.map((draft) => (
                    <tr
                      key={draft.id}
                      className="hover:bg-[#1D1A20]/50 transition-colors group cursor-pointer"
                      onClick={() => handleOpenReview(draft)}
                    >
                      <td className="py-3.5 px-4 font-medium text-[#F5F1EA]">
                        <div className="flex items-center gap-2">
                          <Building size={15} className="text-[#E8B968] flex-shrink-0" />
                          <div>
                            <p className="text-[14px] font-semibold text-[#F5F1EA]">
                              {draft.company_name || "Business Prospect"}
                            </p>
                            {draft.lead_domain && (
                              <p className="text-[11px] text-[#A69EAA] font-mono">{draft.lead_domain}</p>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="py-3.5 px-4 text-[#B7AFBA] font-mono text-[12px]">
                        {draft.recipient_email}
                      </td>
                      <td className="py-3.5 px-4 max-w-[280px]">
                        <p className="text-[#F5F1EA] font-medium truncate">{draft.subject}</p>
                        <p className="text-[11px] text-[#A69EAA] truncate mt-0.5">{draft.body_text}</p>
                      </td>
                      <td className="py-3.5 px-4">{renderStatusBadge(draft.status)}</td>
                      <td className="py-3.5 px-4 text-[#A69EAA] text-[12px] whitespace-nowrap">
                        {new Date(draft.created_at).toLocaleDateString(undefined, {
                          month: "short",
                          day: "numeric",
                        })}
                      </td>
                      <td
                        className="py-3.5 px-4 text-right whitespace-nowrap"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handleOpenReview(draft)}
                            className="px-3 py-1.5 rounded-[8px] bg-[#111013] border border-[#242126] hover:border-[#E8B968]/50 text-[12px] text-[#F5F1EA] font-medium transition-all"
                          >
                            Review
                          </button>

                          {draft.status === "pending_approval" && (
                            <>
                              <button
                                onClick={() => setApproveConfirmDraft(draft)}
                                className="px-3 py-1.5 rounded-[8px] bg-[#39C98A]/20 hover:bg-[#39C98A]/30 border border-[#39C98A]/40 text-[#39C98A] text-[12px] font-semibold transition-all"
                              >
                                Approve
                              </button>
                              <button
                                onClick={() => {
                                  setRejectModalDraft(draft);
                                  setRejectionReason("");
                                }}
                                className="px-3 py-1.5 rounded-[8px] bg-[#F87171]/15 hover:bg-[#F87171]/25 border border-[#F87171]/30 text-[#F87171] text-[12px] font-medium transition-all"
                              >
                                Reject
                              </button>
                            </>
                          )}

                          {(draft.status === "approved" || draft.status === "rejected") && (
                            <button
                              onClick={() => setResetModalDraft(draft)}
                              className="px-3 py-1.5 rounded-[8px] bg-[#242126] hover:bg-[#302A30] text-[#B7AFBA] hover:text-[#F5F1EA] text-[12px] transition-all"
                            >
                              Reset
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile Card List View */}
            <div className="block md:hidden divide-y divide-[#242126]">
              {drafts.map((draft) => (
                <div
                  key={draft.id}
                  onClick={() => handleOpenReview(draft)}
                  className="p-4 space-y-3 cursor-pointer hover:bg-[#1D1A20]/40 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h4 className="text-[15px] font-semibold text-[#F5F1EA]">
                        {draft.company_name || "Business Prospect"}
                      </h4>
                      <p className="text-[12px] text-[#A69EAA] font-mono mt-0.5">{draft.recipient_email}</p>
                    </div>
                    {renderStatusBadge(draft.status)}
                  </div>

                  <div>
                    <p className="text-[13px] font-medium text-[#F5F1EA] line-clamp-1">{draft.subject}</p>
                    <p className="text-[12px] text-[#B7AFBA] line-clamp-2 mt-1">{draft.body_text}</p>
                  </div>

                  <div
                    className="flex items-center justify-between gap-2 pt-2 border-t border-[#242126]/60"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={() => handleOpenReview(draft)}
                      className="px-3 py-1.5 rounded-[8px] bg-[#111013] border border-[#242126] text-[12px] text-[#F5F1EA]"
                    >
                      Review
                    </button>

                    <div className="flex items-center gap-2">
                      {draft.status === "pending_approval" && (
                        <>
                          <button
                            onClick={() => setApproveConfirmDraft(draft)}
                            className="px-3 py-1.5 rounded-[8px] bg-[#39C98A]/20 border border-[#39C98A]/40 text-[#39C98A] text-[12px] font-semibold"
                          >
                            Approve
                          </button>
                          <button
                            onClick={() => {
                              setRejectModalDraft(draft);
                              setRejectionReason("");
                            }}
                            className="px-3 py-1.5 rounded-[8px] bg-[#F87171]/15 border border-[#F87171]/30 text-[#F87171] text-[12px]"
                          >
                            Reject
                          </button>
                        </>
                      )}
                      {(draft.status === "approved" || draft.status === "rejected") && (
                        <button
                          onClick={() => setResetModalDraft(draft)}
                          className="px-3 py-1.5 rounded-[8px] bg-[#242126] text-[#B7AFBA] text-[12px]"
                        >
                          Reset
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 6. Draft Review Slide-over Panel */}
      {selectedDraft && (
        <div className="fixed inset-0 z-50 flex items-center justify-end bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-2xl h-full bg-[#171519] border-l border-[#302A30] shadow-2xl flex flex-col overflow-hidden">
            {/* Panel Header */}
            <div className="p-6 border-b border-[#242126] flex items-center justify-between bg-[#111013]/60">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-[18px] font-semibold text-[#F5F1EA]">
                    {selectedDraft.company_name || "Lead Outreach Draft"}
                  </h3>
                  {selectedDraft.lead_domain && (
                    <span className="text-[11px] font-mono text-[#A69EAA] px-2 py-0.5 rounded bg-[#171519] border border-[#242126]">
                      {selectedDraft.lead_domain}
                    </span>
                  )}
                </div>
                <p className="text-[12px] text-[#A69EAA] mt-1 font-mono">
                  Recipient: <span className="text-[#F5F1EA]">{selectedDraft.recipient_email}</span>
                </p>
              </div>

              <div className="flex items-center gap-3">
                {renderStatusBadge(selectedDraft.status)}
                <button
                  onClick={handleCloseReview}
                  className="p-1.5 rounded-[8px] text-[#77717C] hover:text-[#F5F1EA] hover:bg-[#242126] transition-all"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Panel Body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {/* Evidence Section: WHY this email was generated */}
              <div className="p-4 rounded-[12px] bg-[#1D1A20] border border-[#9D71E8]/30 relative overflow-hidden">
                <div className="flex items-center gap-2 mb-2 text-[#9D71E8]">
                  <Sparkles size={16} />
                  <span className="text-[12px] font-bold uppercase tracking-wider">
                    Observable Technical Evidence (Why this email was generated)
                  </span>
                </div>

                <div className="text-[13px] text-[#B7AFBA] space-y-2">
                  {selectedDraft.evidence ? (
                    <div className="space-y-1.5">
                      {Object.entries(selectedDraft.evidence).map(([key, val]) => (
                        <div key={key} className="flex items-start gap-2">
                          <span className="text-[#E8B968] font-mono text-[11px]">▪</span>
                          <span className="font-semibold text-[#F5F1EA]">{key.replace(/_/g, " ")}:</span>
                          <span className="text-[#B7AFBA]">{typeof val === "object" ? JSON.stringify(val) : String(val)}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="italic text-[#77717C]">
                      Factual basis recorded during Phase 2 technical website audit.
                    </p>
                  )}
                </div>
              </div>

              {/* Email Content Section */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-semibold text-[#F5F1EA] uppercase tracking-wider">
                    Email Draft Content
                  </span>

                  {selectedDraft.status === "pending_approval" && !isEditing && (
                    <button
                      onClick={() => setIsEditing(true)}
                      className="text-[12px] font-medium text-[#E8B968] hover:underline flex items-center gap-1.5"
                    >
                      <Edit3 size={13} />
                      <span>Edit Draft</span>
                    </button>
                  )}
                </div>

                {isEditing ? (
                  /* Edit Form */
                  <div className="space-y-3 p-4 rounded-[12px] bg-[#111013] border border-[#E8B968]/40">
                    <div>
                      <label className="text-[11px] font-semibold text-[#A69EAA] uppercase block mb-1">
                        Subject Line
                      </label>
                      <input
                        type="text"
                        value={editSubject}
                        onChange={(e) => setEditSubject(e.target.value)}
                        className="w-full h-[38px] px-3 rounded-[8px] bg-[#171519] border border-[#242126] text-[13px] text-[#F5F1EA] focus:outline-none focus:border-[#E8B968]"
                      />
                    </div>

                    <div>
                      <label className="text-[11px] font-semibold text-[#A69EAA] uppercase block mb-1">
                        Body Content (Plain Text)
                      </label>
                      <textarea
                        rows={8}
                        value={editBody}
                        onChange={(e) => setEditBody(e.target.value)}
                        className="w-full p-3 rounded-[8px] bg-[#171519] border border-[#242126] text-[13px] text-[#F5F1EA] focus:outline-none focus:border-[#E8B968] leading-relaxed resize-y font-sans"
                      />
                    </div>

                    <div className="flex items-center justify-end gap-2 pt-2">
                      <button
                        onClick={() => {
                          setIsEditing(false);
                          setEditSubject(selectedDraft.subject);
                          setEditBody(selectedDraft.body_text);
                        }}
                        className="px-3.5 py-1.5 rounded-[8px] text-[12px] text-[#B7AFBA] hover:text-[#F5F1EA]"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleSaveEdit}
                        disabled={actionLoading !== null}
                        className="px-4 py-1.5 rounded-[8px] bg-[#E8B968] text-[#111013] font-semibold text-[12px] hover:bg-[#F5CC7A] transition-all"
                      >
                        {actionLoading ? "Saving..." : "Save Changes"}
                      </button>
                    </div>
                  </div>
                ) : (
                  /* Static View */
                  <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] space-y-3">
                    <div>
                      <span className="text-[11px] font-semibold text-[#A69EAA] uppercase block">
                        Subject:
                      </span>
                      <p className="text-[14px] font-semibold text-[#F5F1EA] mt-0.5">
                        {selectedDraft.subject}
                      </p>
                    </div>

                    <div className="pt-2 border-t border-[#242126]">
                      <span className="text-[11px] font-semibold text-[#A69EAA] uppercase block mb-1">
                        Body:
                      </span>
                      <p className="text-[13px] text-[#B7AFBA] whitespace-pre-wrap leading-relaxed">
                        {selectedDraft.body_text}
                      </p>
                    </div>
                  </div>
                )}
              </div>

              {/* Metadata & Audit Section */}
              <div className="p-4 rounded-[12px] bg-[#111013] border border-[#242126] text-[12px] space-y-2">
                <span className="text-[11px] font-semibold text-[#A69EAA] uppercase block mb-1">
                  Draft Lifecycle & Audit Log
                </span>
                <div className="flex justify-between text-[#B7AFBA]">
                  <span>Draft ID:</span>
                  <span className="font-mono text-[#F5F1EA]">{selectedDraft.id}</span>
                </div>
                <div className="flex justify-between text-[#B7AFBA]">
                  <span>Created:</span>
                  <span>{new Date(selectedDraft.created_at).toLocaleString()}</span>
                </div>
                <div className="flex justify-between text-[#B7AFBA]">
                  <span>Updated:</span>
                  <span>{new Date(selectedDraft.updated_at).toLocaleString()}</span>
                </div>

                {selectedDraft.approved_at && (
                  <div className="pt-2 border-t border-[#242126] text-[#39C98A] space-y-1">
                    <div className="flex justify-between font-semibold">
                      <span>Gate 2 Approved By:</span>
                      <span>{selectedDraft.approved_by || "Owner"}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Approved Timestamp:</span>
                      <span>{new Date(selectedDraft.approved_at).toLocaleString()}</span>
                    </div>
                  </div>
                )}

                {selectedDraft.rejected_at && (
                  <div className="pt-2 border-t border-[#242126] text-[#F87171] space-y-1">
                    <div className="flex justify-between font-semibold">
                      <span>Rejected By:</span>
                      <span>{selectedDraft.rejected_by || "Owner"}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Reason:</span>
                      <span className="italic">{selectedDraft.rejection_reason}</span>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Panel Footer Controls */}
            <div className="p-6 border-t border-[#242126] bg-[#111013]/60 flex items-center justify-between gap-3">
              <button
                onClick={handleCloseReview}
                className="px-4 py-2 rounded-[10px] bg-[#171519] border border-[#242126] text-[#B7AFBA] hover:text-[#F5F1EA] text-[13px] font-medium"
              >
                Close
              </button>

              <div className="flex items-center gap-3">
                {selectedDraft.status === "pending_approval" && (
                  <>
                    <button
                      onClick={() => {
                        setRejectModalDraft(selectedDraft);
                        setRejectionReason("");
                      }}
                      className="px-4 py-2 rounded-[10px] bg-[#F87171]/15 hover:bg-[#F87171]/25 border border-[#F87171]/30 text-[#F87171] text-[13px] font-medium transition-all"
                    >
                      Reject Draft
                    </button>
                    <button
                      onClick={() => setApproveConfirmDraft(selectedDraft)}
                      className="px-5 py-2 rounded-[10px] bg-[#39C98A] hover:bg-[#34B77D] text-[#111013] text-[13px] font-semibold transition-all shadow-md shadow-[#39C98A]/20"
                    >
                      Approve Draft
                    </button>
                  </>
                )}

                {(selectedDraft.status === "approved" || selectedDraft.status === "rejected") && (
                  <button
                    onClick={() => setResetModalDraft(selectedDraft)}
                    className="px-4 py-2 rounded-[10px] bg-[#242126] hover:bg-[#302A30] text-[#F5F1EA] text-[13px] font-medium transition-all"
                  >
                    Reset to Pending Approval
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 7. Approve Confirmation Modal */}
      {approveConfirmDraft && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fade-in">
          <div className="w-full max-w-lg bg-[#171519] border border-[#302A30] rounded-[16px] p-6 shadow-2xl space-y-4">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-[10px] bg-[#39C98A]/15 text-[#39C98A] flex items-center justify-center flex-shrink-0">
                <CheckCircle2 size={22} />
              </div>
              <div>
                <h3 className="text-[17px] font-semibold text-[#F5F1EA]">
                  Confirm Gate 2 Approval
                </h3>
                <p className="text-[13px] text-[#B7AFBA] mt-0.5">
                  Confirm human clearance for this personalized outreach email.
                </p>
              </div>
            </div>

            <div className="p-3.5 rounded-[10px] bg-[#111013] border border-[#242126] text-[13px] space-y-2">
              <div>
                <span className="text-[11px] font-semibold text-[#A69EAA] uppercase block">
                  Company / Recipient:
                </span>
                <p className="text-[#F5F1EA] font-medium">
                  {approveConfirmDraft.company_name || "Company"} ({approveConfirmDraft.recipient_email})
                </p>
              </div>
              <div>
                <span className="text-[11px] font-semibold text-[#A69EAA] uppercase block">
                  Subject:
                </span>
                <p className="text-[#F5F1EA] truncate">{approveConfirmDraft.subject}</p>
              </div>
              <div>
                <span className="text-[11px] font-semibold text-[#A69EAA] uppercase block">
                  Preview:
                </span>
                <p className="text-[#B7AFBA] line-clamp-3 text-[12px]">
                  {approveConfirmDraft.body_text}
                </p>
              </div>
            </div>

            <div className="p-3 rounded-[10px] bg-[#39C98A]/10 border border-[#39C98A]/30 text-[12px] text-[#39C98A]">
              <strong>Note:</strong> Approving authorizes the draft for downstream Safety Controller validation.
              It does NOT dispatch an email.
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => setApproveConfirmDraft(null)}
                className="px-4 py-2 rounded-[8px] text-[13px] text-[#B7AFBA] hover:text-[#F5F1EA]"
              >
                Cancel
              </button>
              <button
                onClick={() => handleApprove(approveConfirmDraft)}
                disabled={actionLoading !== null}
                className="px-5 py-2 rounded-[8px] bg-[#39C98A] text-[#111013] font-semibold text-[13px] hover:bg-[#34B77D] transition-all"
              >
                {actionLoading ? "Approving..." : "Confirm Gate 2 Approval"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 8. Reject Reason Modal */}
      {rejectModalDraft && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fade-in">
          <div className="w-full max-w-lg bg-[#171519] border border-[#302A30] rounded-[16px] p-6 shadow-2xl space-y-4">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-[10px] bg-[#F87171]/15 text-[#F87171] flex items-center justify-center flex-shrink-0">
                <XCircle size={22} />
              </div>
              <div>
                <h3 className="text-[17px] font-semibold text-[#F5F1EA]">
                  Reject Outreach Draft
                </h3>
                <p className="text-[13px] text-[#B7AFBA] mt-0.5">
                  A rejection reason is required to maintain the audit trail.
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-[11px] font-semibold text-[#A69EAA] uppercase block">
                Rejection Reason (Required)
              </label>
              <textarea
                rows={3}
                placeholder="e.g. Inappropriate tone, incorrect niche, or contact no longer relevant..."
                value={rejectionReason}
                onChange={(e) => setRejectionReason(e.target.value)}
                className="w-full p-3 rounded-[8px] bg-[#111013] border border-[#242126] text-[13px] text-[#F5F1EA] focus:outline-none focus:border-[#F87171] placeholder-[#77717C] leading-relaxed"
              />
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => setRejectModalDraft(null)}
                className="px-4 py-2 rounded-[8px] text-[13px] text-[#B7AFBA] hover:text-[#F5F1EA]"
              >
                Cancel
              </button>
              <button
                onClick={() => handleReject(rejectModalDraft)}
                disabled={actionLoading !== null || !rejectionReason.trim()}
                className="px-5 py-2 rounded-[8px] bg-[#F87171] text-[#111013] font-semibold text-[13px] hover:bg-[#EF4444] transition-all disabled:opacity-50"
              >
                {actionLoading ? "Rejecting..." : "Confirm Rejection"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 9. Reset Warning Modal */}
      {resetModalDraft && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fade-in">
          <div className="w-full max-w-lg bg-[#171519] border border-[#302A30] rounded-[16px] p-6 shadow-2xl space-y-4">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-[10px] bg-[#E8B968]/15 text-[#E8B968] flex items-center justify-center flex-shrink-0">
                <RotateCw size={22} />
              </div>
              <div>
                <h3 className="text-[17px] font-semibold text-[#F5F1EA]">
                  Reset Draft to Pending Approval
                </h3>
                <p className="text-[13px] text-[#B7AFBA] mt-0.5">
                  Re-evaluate or modify an approved or rejected draft.
                </p>
              </div>
            </div>

            <div className="p-3.5 rounded-[10px] bg-[#E8B968]/10 border border-[#E8B968]/30 text-[13px] text-[#F5CC7A] leading-relaxed">
              <strong>Warning:</strong> Resetting this draft removes its current approval and requires fresh owner approval before it can ever pass Gate 2.
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => setResetModalDraft(null)}
                className="px-4 py-2 rounded-[8px] text-[13px] text-[#B7AFBA] hover:text-[#F5F1EA]"
              >
                Cancel
              </button>
              <button
                onClick={() => handleReset(resetModalDraft)}
                disabled={actionLoading !== null}
                className="px-5 py-2 rounded-[8px] bg-[#E8B968] text-[#111013] font-semibold text-[13px] hover:bg-[#F5CC7A] transition-all"
              >
                {actionLoading ? "Resetting..." : "Confirm Reset"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function OutreachPage() {
  return (
    <Suspense
      fallback={
        <div className="p-12 text-center text-[#B7AFBA]">
          <RotateCw className="w-8 h-8 animate-spin mx-auto text-[#E8B968] mb-3" />
          <p className="text-[14px]">Loading Outreach Console...</p>
        </div>
      }
    >
      <OutreachContent />
    </Suspense>
  );
}
