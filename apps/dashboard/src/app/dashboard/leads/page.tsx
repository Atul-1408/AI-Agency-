"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import {
  api,
  type Lead,
} from "@/lib/api";
import {
  Search,
  Plus,
  ExternalLink,
  Globe,
  Mail,
  Check,
  X,
  ChevronRight,
  Zap,
  LayoutGrid,
  Table as TableIcon,
} from "lucide-react";

function LeadsContent() {
  const searchParams = useSearchParams();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);

  // View state
  const [viewMode, setViewMode] = useState<"kanban" | "table">("kanban");
  const [activeTab, setActiveTab] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [minScore, setMinScore] = useState<number>(0);

  // Modals & Drawers
  const actionParam = searchParams.get("action");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [showDiscoverModal, setShowDiscoverModal] = useState<boolean>(() => actionParam === "discover");
  const [showManualModal, setShowManualModal] = useState<boolean>(() => actionParam === "manual");
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Discover Form
  const [discoverQuery, setDiscoverQuery] = useState("dentists in Denver");
  const [discoverLocation, setDiscoverLocation] = useState("Denver, CO");
  const [discoverLimit, setDiscoverLimit] = useState(10);
  const [discoverProvider, setDiscoverProvider] = useState("google_places");
  const [discoverMessage, setDiscoverMessage] = useState<string | null>(null);

  // Manual Form
  const [manualForm, setManualForm] = useState({
    company_name: "",
    website_url: "",
    phone: "",
    address: "",
    city: "",
    industry: "",
    notes: "",
  });

  const fetchLeads = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.leads.list({
        page: 1,
        page_size: 100,
        status: activeTab === "all" ? undefined : activeTab,
        search: searchQuery || undefined,
        min_score: minScore > 0 ? minScore : undefined,
      });
      setLeads(res?.items || []);

      const selId = searchParams.get("selected");
      if (selId && res?.items) {
        const found = res.items.find((l) => l.id === selId);
        if (found) setSelectedLead(found);
      }
    } catch {
      // Safe fallback
    } finally {
      setLoading(false);
    }
  }, [activeTab, minScore, searchQuery, searchParams]);

  useEffect(() => {
    let mounted = true;
    api.leads
      .list({
        page: 1,
        page_size: 100,
        status: activeTab === "all" ? undefined : activeTab,
        search: searchQuery || undefined,
        min_score: minScore > 0 ? minScore : undefined,
      })
      .then((res) => {
        if (mounted) {
          setLeads(res?.items || []);
          const selId = searchParams.get("selected");
          if (selId && res?.items) {
            const found = res.items.find((l) => l.id === selId);
            if (found) setSelectedLead(found);
          }
          setLoading(false);
        }
      })
      .catch(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [activeTab, minScore, searchQuery, searchParams]);

  const handleApprove = async (leadId: string) => {
    setActionLoading(leadId);
    try {
      const updated = await api.leads.approve(leadId);
      setLeads((prev) => prev.map((l) => (l.id === leadId ? updated : l)));
      if (selectedLead?.id === leadId) setSelectedLead(updated);
    } catch {
      // fallback
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async (leadId: string) => {
    setActionLoading(leadId);
    try {
      const updated = await api.leads.reject(leadId, "Disqualified by agency owner");
      setLeads((prev) => prev.map((l) => (l.id === leadId ? updated : l)));
      if (selectedLead?.id === leadId) setSelectedLead(updated);
    } catch {
      // fallback
    } finally {
      setActionLoading(null);
    }
  };

  const handleDiscoverSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading("discover");
    setDiscoverMessage(null);
    try {
      await api.leads.discover({
        query: discoverQuery,
        location: discoverLocation,
        limit: discoverLimit,
        provider: discoverProvider,
      });
      setDiscoverMessage("Discovery enqueued to ARQ worker.");
      setTimeout(() => {
        setShowDiscoverModal(false);
        setDiscoverMessage(null);
        fetchLeads();
      }, 1200);
    } catch {
      setShowDiscoverModal(false);
    } finally {
      setActionLoading(null);
    }
  };

  const handleManualSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading("manual");
    try {
      await api.leads.createManual(manualForm);
      setShowManualModal(false);
      setManualForm({
        company_name: "",
        website_url: "",
        phone: "",
        address: "",
        city: "",
        industry: "",
        notes: "",
      });
      fetchLeads();
    } catch {
      setShowManualModal(false);
    } finally {
      setActionLoading(null);
    }
  };

  const kanbanColumns = [
    { id: "discovered", label: "Discovered", dot: "#B7AFBA" },
    { id: "researched", label: "Researched", dot: "#8B6FB8" },
    { id: "qualified", label: "Qualified", dot: "#39C98A" },
    { id: "approved", label: "Approved ✓", dot: "#39C98A" },
    { id: "low_priority", label: "Low Priority", dot: "#E8B968" },
  ];

  return (
    <div className="pb-12 animate-fade-in">
      {/* 12. Editorial Page Header with Strict Spacing */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-[32px] pb-2 border-b border-[#242126]">
        <div>
          <p className="text-[12px] font-semibold tracking-[0.16em] uppercase text-[#E8B968] mb-[8px]">
            PHASE 2: LEAD RESEARCH AGENT
          </p>

          <h1 className="font-display text-[42px] md:text-[48px] font-normal text-[#F5F1EA] leading-[1.05] mb-[8px] tracking-tight">
            Lead Pipeline
          </h1>

          <p className="text-[15px] md:text-[16px] text-[#B7AFBA] leading-[1.5] max-w-2xl">
            Autonomous prospect discovery, SSRF-protected website audits, and deterministic qualification scoring.
          </p>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-3 flex-wrap">
          {/* View Mode Toggle */}
          <div className="flex items-center p-1 rounded-[10px] bg-[#171519] border border-[#302A30]">
            <button
              type="button"
              onClick={() => setViewMode("kanban")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-[8px] text-[13px] font-medium transition-colors ${
                viewMode === "kanban"
                  ? "bg-[#242126] text-[#F5F1EA]"
                  : "text-[#77717C] hover:text-[#B7AFBA]"
              }`}
            >
              <LayoutGrid size={14} />
              <span>Kanban</span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode("table")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-[8px] text-[13px] font-medium transition-colors ${
                viewMode === "table"
                  ? "bg-[#242126] text-[#F5F1EA]"
                  : "text-[#77717C] hover:text-[#B7AFBA]"
              }`}
            >
              <TableIcon size={14} />
              <span>Table</span>
            </button>
          </div>

          <button
            type="button"
            onClick={() => setShowDiscoverModal(true)}
            className="h-[44px] px-5 rounded-[10px] bg-[#E8B968] hover:bg-[#F5CC7A] text-[#17130D] text-[13px] font-semibold flex items-center gap-2 transition-all shadow-[0_2px_12px_rgba(232,185,105,0.2)]"
          >
            <Search size={14} />
            <span>Discover Prospects</span>
          </button>

          <button
            type="button"
            onClick={() => setShowManualModal(true)}
            className="h-[44px] px-4 rounded-[10px] bg-[#171519] hover:bg-[#242126] border border-[#302A30] text-[#F5F1EA] text-[13px] font-semibold flex items-center gap-2 transition-colors"
          >
            <Plus size={14} />
            <span>Add Lead</span>
          </button>
        </div>
      </div>

      {/* Filter Bar with Generous Breathing Room */}
      <div className="p-4 rounded-[14px] bg-[#171519] border border-[#302A30] flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-4 mb-[24px]">
        {/* Status Tabs */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 lg:pb-0 scrollbar-none">
          {[
            { id: "all", label: "All Leads" },
            { id: "discovered", label: "Discovered" },
            { id: "researched", label: "Researched" },
            { id: "qualified", label: "Qualified (≥60)" },
            { id: "approved", label: "Approved" },
            { id: "low_priority", label: "Low Priority" },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`h-[38px] px-4 rounded-[8px] text-[13px] font-medium transition-all flex-shrink-0 whitespace-nowrap flex items-center justify-center ${
                activeTab === tab.id
                  ? "bg-[rgba(232,185,105,0.15)] text-[#F5CC7A] border border-[rgba(232,185,105,0.35)] font-semibold shadow-sm"
                  : "text-[#B7AFBA] hover:text-[#F5F1EA] hover:bg-[#242126]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search & Min Score */}
        <div className="flex items-center gap-3">
          <div className="relative w-full lg:w-64">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#77717C]" />
            <input
              type="text"
              placeholder="Search companies or domain..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full h-[36px] pl-9 pr-3 rounded-[8px] bg-[#111013] border border-[#242126] text-[13px] text-[#F5F1EA] placeholder-[#77717C] focus:outline-none focus:border-[#E8B968]/50"
            />
          </div>

          <div className="flex items-center gap-2 px-3 h-[36px] rounded-[8px] bg-[#111013] border border-[#242126] flex-shrink-0 text-[12px]">
            <span className="text-[#77717C]">Min Score:</span>
            <select
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
              className="bg-transparent text-[#E8B968] font-semibold focus:outline-none cursor-pointer"
            >
              <option value="0" className="bg-[#111013]">Any (0+)</option>
              <option value="50" className="bg-[#111013]">50+</option>
              <option value="60" className="bg-[#111013]">60+ (Qualified)</option>
              <option value="80" className="bg-[#111013]">80+ (High Intent)</option>
            </select>
          </div>
        </div>
      </div>

      {/* Main View: Kanban vs Table */}
      {leads.length === 0 && !loading ? (
        /* Spacious Empty State */
        <div className="py-[64px] rounded-[14px] bg-[#171519] border border-[#302A30] flex flex-col items-center justify-center text-center p-8">
          <div className="w-[56px] h-[56px] rounded-[14px] bg-[#1D1A1F] border border-[#302A30] flex items-center justify-center text-[#77717C] mb-4">
            <Globe size={24} />
          </div>
          <h4 className="text-[19px] font-semibold text-[#F5F1EA] tracking-tight">
            No leads discovered yet
          </h4>
          <p className="text-[14px] text-[#77717C] mt-2 max-w-md leading-relaxed">
            Run a discovery agent or add a lead manually to populate the research and qualification pipeline.
          </p>
          <div className="mt-[24px]">
            <button
              type="button"
              onClick={() => setShowDiscoverModal(true)}
              className="h-[44px] px-6 rounded-[10px] bg-[#E8B968] hover:bg-[#F5CC7A] text-[#17130D] text-[13px] font-semibold flex items-center gap-2 transition-all shadow-[0_2px_12px_rgba(232,185,105,0.2)]"
            >
              <Search size={14} />
              <span>Discover Prospects</span>
            </button>
          </div>
        </div>
      ) : viewMode === "kanban" ? (
        /* Kanban Grid with 20px gap */
        <div className="grid grid-cols-1 md:grid-cols-5 gap-[20px]">
          {kanbanColumns.map((col) => {
            const colLeads = leads.filter((l) => {
              if (col.id === "low_priority") {
                return (
                  l.status === "low_priority" ||
                  l.status === "disqualified" ||
                  l.status === "rejected"
                );
              }
              return l.status === col.id;
            });

            return (
              <div key={col.id} className="flex flex-col gap-[14px]">
                {/* Column Top Header */}
                <div className="h-[44px] px-4 rounded-[10px] bg-[#171519] border border-[#302A30] flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: col.dot }}
                    />
                    <span className="text-[13px] font-semibold text-[#F5F1EA]">
                      {col.label}
                    </span>
                  </div>
                  <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-[#1D1A1F] text-[#B7AFBA] border border-[#242126]">
                    {colLeads.length}
                  </span>
                </div>

                {/* Column Cards */}
                <div className="space-y-[12px] min-h-[300px]">
                  {colLeads.length === 0 ? (
                    <div className="h-32 rounded-[12px] border border-dashed border-[#242126] bg-[#111013]/40 flex flex-col items-center justify-center p-4 text-center">
                      <span className="text-[12px] text-[#77717C]">No leads</span>
                      <span className="text-[11px] text-[#77717C]/60 mt-0.5">Stage clear</span>
                    </div>
                  ) : (
                    colLeads.map((lead) => (
                      <div
                        key={lead.id}
                        onClick={() => setSelectedLead(lead)}
                        className={`p-[18px] rounded-[12px] bg-[#171519] border transition-all duration-180 cursor-pointer group hover:-translate-y-[2px] ${
                          selectedLead?.id === lead.id
                            ? "border-[#E8B968] shadow-[0_0_18px_rgba(232,185,105,0.12)]"
                            : "border-[#302A30] hover:border-[#E8B968]/40"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <h4 className="text-[14px] font-semibold text-[#F5F1EA] group-hover:text-[#F5CC7A] transition-colors leading-tight">
                              {lead.company_name}
                            </h4>
                            <p className="text-[12px] text-[#77717C] flex items-center gap-1 mt-1 truncate max-w-[140px]">
                              <Globe size={11} />
                              <span className="truncate">{lead.domain}</span>
                            </p>
                          </div>

                          <div
                            className={`px-2 py-0.5 rounded-[6px] text-[11px] font-bold border ${
                              lead.qualification_score >= 80
                                ? "bg-[#39C98A]/10 text-[#39C98A] border-[#39C98A]/30"
                                : lead.qualification_score >= 50
                                ? "bg-[#E8B968]/10 text-[#E8B968] border-[#E8B968]/30"
                                : "bg-[#E06B6B]/10 text-[#E06B6B] border-[#E06B6B]/30"
                            }`}
                          >
                            {lead.qualification_score}
                          </div>
                        </div>

                        {/* Audit Indicators */}
                        {lead.research && (
                          <div className="mt-3 flex items-center gap-1.5 flex-wrap text-[10px]">
                            <span
                              className={`px-1.5 py-0.5 rounded border ${
                                lead.research.is_responsive === false
                                  ? "bg-[#E06B6B]/10 text-[#E06B6B] border-[#E06B6B]/25"
                                  : "bg-[#39C98A]/10 text-[#39C98A] border-[#39C98A]/25"
                              }`}
                            >
                              {lead.research.is_responsive === false ? "Non-Responsive" : "Mobile OK"}
                            </span>
                            {lead.research.copyright_year && (
                              <span className="px-1.5 py-0.5 rounded bg-[#111013] text-[#B7AFBA] border border-[#242126]">
                                © {lead.research.copyright_year}
                              </span>
                            )}
                          </div>
                        )}

                        <div className="mt-3 pt-2 border-t border-[#242126] flex items-center justify-between text-[11px] text-[#77717C]">
                          <span>{lead.city || lead.industry || "Commercial"}</span>
                          <span className="text-[#E8B968] group-hover:translate-x-0.5 transition-transform inline-flex items-center gap-0.5">
                            Inspect <ChevronRight size={11} />
                          </span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* Table View */
        <div className="p-4 rounded-[14px] bg-[#171519] border border-[#302A30] overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead className="text-[11px] font-semibold text-[#77717C] uppercase tracking-wider border-b border-[#242126]">
              <tr>
                <th className="py-3 px-4">Company & Domain</th>
                <th className="py-3 px-4">Contact</th>
                <th className="py-3 px-4">Location / Sector</th>
                <th className="py-3 px-4">Technical Score</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#242126]/60">
              {leads.map((lead) => (
                <tr
                  key={lead.id}
                  onClick={() => setSelectedLead(lead)}
                  className="hover:bg-[#1D1A1F]/50 transition-colors cursor-pointer group"
                >
                  <td className="py-3.5 px-4">
                    <span className="font-semibold text-[#F5F1EA] group-hover:text-[#F5CC7A] transition-colors block">
                      {lead.company_name}
                    </span>
                    <span className="text-[12px] text-[#77717C]">{lead.domain}</span>
                  </td>
                  <td className="py-3.5 px-4 text-[12px] text-[#B7AFBA]">
                    {lead.email ? (
                      <span className="flex items-center gap-1.5">
                        <Mail size={12} className="text-[#E8B968]" />
                        <span>{lead.email}</span>
                      </span>
                    ) : (
                      <span className="text-[#77717C]">No email</span>
                    )}
                  </td>
                  <td className="py-3.5 px-4 text-[12px] text-[#B7AFBA]">
                    {lead.city || lead.industry || "General"}
                  </td>
                  <td className="py-3.5 px-4">
                    <span
                      className={`px-2 py-0.5 rounded-[6px] text-[11px] font-bold border ${
                        lead.qualification_score >= 80
                          ? "bg-[#39C98A]/10 text-[#39C98A] border-[#39C98A]/30"
                          : lead.qualification_score >= 50
                          ? "bg-[#E8B968]/10 text-[#E8B968] border-[#E8B968]/30"
                          : "bg-[#E06B6B]/10 text-[#E06B6B] border-[#E06B6B]/30"
                      }`}
                    >
                      {lead.qualification_score} / 100
                    </span>
                  </td>
                  <td className="py-3.5 px-4">
                    <span className="text-[11px] font-semibold text-[#B7AFBA] uppercase">
                      {lead.status}
                    </span>
                  </td>
                  <td className="py-3.5 px-4 text-right">
                    <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        onClick={() => handleApprove(lead.id)}
                        className="p-1.5 rounded-[6px] bg-[#39C98A]/10 text-[#39C98A] border border-[#39C98A]/25 hover:bg-[#39C98A]/20"
                        title="Approve for Outreach"
                      >
                        <Check size={12} strokeWidth={2.5} />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleReject(lead.id)}
                        className="p-1.5 rounded-[6px] bg-[#E06B6B]/10 text-[#E06B6B] border border-[#E06B6B]/25 hover:bg-[#E06B6B]/20"
                        title="Disqualify"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Slide-over Lead Dossier */}
      {selectedLead && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/70 backdrop-blur-xs">
          <div className="w-full max-w-xl bg-[#111013] border-l border-[#242126] h-full overflow-y-auto p-8 space-y-6 shadow-2xl animate-fade-in">
            <div className="flex items-start justify-between pb-4 border-b border-[#242126]">
              <div>
                <span className="text-[11px] font-semibold uppercase tracking-wider text-[#E8B968]">
                  LEAD AUDIT DOSSIER
                </span>
                <h2 className="text-[22px] font-semibold text-[#F5F1EA] mt-1">
                  {selectedLead.company_name}
                </h2>
                <a
                  href={selectedLead.website_url || `https://${selectedLead.domain}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[13px] text-[#E8B968] hover:underline inline-flex items-center gap-1.5 mt-1"
                >
                  <span>{selectedLead.domain}</span>
                  <ExternalLink size={12} />
                </a>
              </div>
              <button
                type="button"
                onClick={() => setSelectedLead(null)}
                className="text-[#77717C] hover:text-[#F5F1EA] p-1"
              >
                ✕
              </button>
            </div>

            {/* Score Banner */}
            <div className="p-5 rounded-[12px] bg-[#171519] border border-[#302A30] flex items-center justify-between">
              <div>
                <span className="text-[11px] font-semibold text-[#77717C] uppercase tracking-wider">
                  Qualification Score
                </span>
                <div className="text-[32px] font-semibold text-[#F5F1EA] leading-none mt-1">
                  {selectedLead.qualification_score} <span className="text-[14px] text-[#77717C]">/ 100</span>
                </div>
              </div>
              <div
                className={`w-12 h-12 rounded-[10px] flex items-center justify-center font-bold text-lg border ${
                  selectedLead.qualification_score >= 80
                    ? "bg-[#39C98A]/10 text-[#39C98A] border-[#39C98A]/30"
                    : selectedLead.qualification_score >= 50
                    ? "bg-[#E8B968]/10 text-[#E8B968] border-[#E8B968]/30"
                    : "bg-[#E06B6B]/10 text-[#E06B6B] border-[#E06B6B]/30"
                }`}
              >
                {selectedLead.qualification_score >= 80 ? "A" : selectedLead.qualification_score >= 50 ? "B" : "C"}
              </div>
            </div>

            {/* Technical Findings if researched */}
            {selectedLead.research && (
              <div className="space-y-4">
                <h4 className="text-[14px] font-semibold text-[#F5F1EA]">
                  Objective Website Findings (SSRF Verified)
                </h4>
                <div className="grid grid-cols-2 gap-3 text-[12px]">
                  <div className="p-3 rounded-[8px] bg-[#171519] border border-[#242126]">
                    <span className="text-[#77717C]">Mobile Responsive</span>
                    <p className={`font-semibold mt-1 ${selectedLead.research.is_responsive === false ? "text-[#E06B6B]" : "text-[#39C98A]"}`}>
                      {selectedLead.research.is_responsive === false ? "Broken / Desktop-only" : "Mobile Optimized"}
                    </p>
                  </div>
                  <div className="p-3 rounded-[8px] bg-[#171519] border border-[#242126]">
                    <span className="text-[#77717C]">SSL Security</span>
                    <p className={`font-semibold mt-1 ${selectedLead.research.has_ssl === false ? "text-[#E06B6B]" : "text-[#39C98A]"}`}>
                      {selectedLead.research.has_ssl === false ? "Missing SSL (HTTP)" : "HTTPS Encrypted"}
                    </p>
                  </div>
                </div>

                {selectedLead.research.audit_findings?.findings && (
                  <div className="p-4 rounded-[10px] bg-[#171519] border border-[#242126] space-y-2">
                    <span className="text-[11px] font-semibold text-[#E8B968] uppercase">Auditor Findings</span>
                    <ul className="space-y-1 text-[13px] text-[#B7AFBA]">
                      {selectedLead.research.audit_findings.findings.map((f, i) => (
                        <li key={i} className="flex items-start gap-2">
                          <span className="text-[#E8B968]">•</span>
                          <span>{f}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Actions */}
            <div className="pt-4 border-t border-[#242126] flex items-center gap-3">
              <button
                type="button"
                disabled={actionLoading === selectedLead.id}
                onClick={() => handleApprove(selectedLead.id)}
                className="flex-1 h-[44px] rounded-[10px] bg-[#E8B968] hover:bg-[#F5CC7A] text-[#17130D] text-[13px] font-semibold flex items-center justify-center gap-2 transition-all disabled:opacity-50"
              >
                <Check size={14} strokeWidth={2.5} />
                <span>{selectedLead.status === "approved" ? "Approved ✓" : "Approve for Outreach"}</span>
              </button>
              <button
                type="button"
                disabled={actionLoading === selectedLead.id}
                onClick={() => handleReject(selectedLead.id)}
                className="h-[44px] px-4 rounded-[10px] bg-[#171519] hover:bg-[#242126] border border-[#302A30] text-[#E06B6B] text-[13px] font-semibold flex items-center gap-1.5 transition-colors disabled:opacity-50"
              >
                <X size={14} />
                <span>Disqualify</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Discover Modal */}
      {showDiscoverModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-xs p-4">
          <div className="w-full max-w-lg rounded-[14px] bg-[#171519] border border-[#302A30] p-6 space-y-4 shadow-2xl animate-fade-in">
            <div className="flex items-center justify-between pb-3 border-b border-[#242126]">
              <h3 className="text-[17px] font-semibold text-[#F5F1EA]">
                Discover Local Business Prospects
              </h3>
              <button
                type="button"
                onClick={() => setShowDiscoverModal(false)}
                className="text-[#77717C] hover:text-[#F5F1EA]"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleDiscoverSubmit} className="space-y-4 text-[13px]">
              <div>
                <label className="block text-[#B7AFBA] font-semibold mb-1">
                  Search Query / Business Vertical *
                </label>
                <input
                  type="text"
                  required
                  value={discoverQuery}
                  onChange={(e) => setDiscoverQuery(e.target.value)}
                  placeholder="e.g. dentists in Denver, hvac in Austin"
                  className="w-full h-[40px] px-3 rounded-[8px] bg-[#111013] border border-[#302A30] text-[#F5F1EA] focus:outline-none focus:border-[#E8B968]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[#B7AFBA] font-semibold mb-1">
                    Location
                  </label>
                  <input
                    type="text"
                    value={discoverLocation}
                    onChange={(e) => setDiscoverLocation(e.target.value)}
                    placeholder="Denver, CO"
                    className="w-full h-[40px] px-3 rounded-[8px] bg-[#111013] border border-[#302A30] text-[#F5F1EA] focus:outline-none focus:border-[#E8B968]"
                  />
                </div>
                <div>
                  <label className="block text-[#B7AFBA] font-semibold mb-1">
                    Batch Limit
                  </label>
                  <select
                    value={discoverLimit}
                    onChange={(e) => setDiscoverLimit(Number(e.target.value))}
                    className="w-full h-[40px] px-3 rounded-[8px] bg-[#111013] border border-[#302A30] text-[#F5F1EA] focus:outline-none"
                  >
                    <option value="5">5 Leads</option>
                    <option value="10">10 Leads</option>
                    <option value="20">20 Leads (Max)</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-[#B7AFBA] font-semibold mb-1">
                  Discovery Provider
                </label>
                <select
                  value={discoverProvider}
                  onChange={(e) => setDiscoverProvider(e.target.value)}
                  className="w-full h-[40px] px-3 rounded-[8px] bg-[#111013] border border-[#302A30] text-[#F5F1EA] focus:outline-none"
                >
                  <option value="google_places">Google Places Provider (SSRF-protected)</option>
                  <option value="manual_entry">Manual Discovery Provider</option>
                </select>
              </div>

              {discoverMessage && (
                <div className="p-3 rounded-[8px] bg-[#39C98A]/10 border border-[#39C98A]/25 text-[12px] text-[#39C98A]">
                  {discoverMessage}
                </div>
              )}

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#242126]">
                <button
                  type="button"
                  onClick={() => setShowDiscoverModal(false)}
                  className="px-4 py-2 rounded-[8px] text-[13px] text-[#B7AFBA] hover:text-[#F5F1EA]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading === "discover"}
                  className="h-[44px] px-5 rounded-[10px] bg-[#E8B968] hover:bg-[#F5CC7A] text-[#17130D] text-[13px] font-semibold flex items-center gap-2 transition-all disabled:opacity-50"
                >
                  <Zap size={14} />
                  <span>Launch Discovery</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Manual Lead Modal */}
      {showManualModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-xs p-4">
          <div className="w-full max-w-lg rounded-[14px] bg-[#171519] border border-[#302A30] p-6 space-y-4 shadow-2xl animate-fade-in">
            <div className="flex items-center justify-between pb-3 border-b border-[#242126]">
              <h3 className="text-[17px] font-semibold text-[#F5F1EA]">
                Add Lead Manually
              </h3>
              <button
                type="button"
                onClick={() => setShowManualModal(false)}
                className="text-[#77717C] hover:text-[#F5F1EA]"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleManualSubmit} className="space-y-3.5 text-[13px]">
              <div>
                <label className="block text-[#B7AFBA] font-semibold mb-1">Company Name *</label>
                <input
                  type="text"
                  required
                  value={manualForm.company_name}
                  onChange={(e) => setManualForm({ ...manualForm, company_name: e.target.value })}
                  placeholder="Apex Dental Studio"
                  className="w-full h-[40px] px-3 rounded-[8px] bg-[#111013] border border-[#302A30] text-[#F5F1EA] focus:outline-none focus:border-[#E8B968]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[#B7AFBA] font-semibold mb-1">Website URL</label>
                  <input
                    type="text"
                    value={manualForm.website_url}
                    onChange={(e) => setManualForm({ ...manualForm, website_url: e.target.value })}
                    placeholder="https://apexdental.com"
                    className="w-full h-[40px] px-3 rounded-[8px] bg-[#111013] border border-[#302A30] text-[#F5F1EA] focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-[#B7AFBA] font-semibold mb-1">City</label>
                  <input
                    type="text"
                    value={manualForm.city}
                    onChange={(e) => setManualForm({ ...manualForm, city: e.target.value })}
                    placeholder="Denver"
                    className="w-full h-[40px] px-3 rounded-[8px] bg-[#111013] border border-[#302A30] text-[#F5F1EA] focus:outline-none"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#242126]">
                <button
                  type="button"
                  onClick={() => setShowManualModal(false)}
                  className="px-4 py-2 rounded-[8px] text-[13px] text-[#B7AFBA] hover:text-[#F5F1EA]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading === "manual"}
                  className="h-[44px] px-5 rounded-[10px] bg-[#E8B968] hover:bg-[#F5CC7A] text-[#17130D] text-[13px] font-semibold flex items-center gap-2 transition-all disabled:opacity-50"
                >
                  <Plus size={14} />
                  <span>Save Lead</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default function LeadsPage() {
  return (
    <Suspense
      fallback={
        <div className="py-24 text-center text-[#77717C] text-[14px]">
          Loading Lead Pipeline...
        </div>
      }
    >
      <LeadsContent />
    </Suspense>
  );
}
