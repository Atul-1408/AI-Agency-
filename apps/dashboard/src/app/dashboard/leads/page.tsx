"use client";

import { useEffect, useState, useMemo } from "react";
import {
  api,
  type Lead,
  type LeadStatus,
} from "@/lib/api";
import {
  Search,
  Filter,
  Plus,
  ExternalLink,
  ShieldCheck,
  ShieldAlert,
  Smartphone,
  Clock,
  CheckCircle2,
  XCircle,
  HelpCircle,
  AlertTriangle,
  RotateCcw,
  Sparkles,
  Globe,
  Building,
  Mail,
  Phone,
  Calendar,
  X,
} from "lucide-react";

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [activeTab, setActiveTab] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [minScore, setMinScore] = useState<number>(0);

  // Modals / Drawers
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [showDiscoverModal, setShowDiscoverModal] = useState(false);
  const [showManualModal, setShowManualModal] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Discover Form
  const [discoverQuery, setDiscoverQuery] = useState("");
  const [discoverLocation, setDiscoverLocation] = useState("");
  const [discoverLimit, setDiscoverLimit] = useState(10);
  const [discoverProvider, setDiscoverProvider] = useState("google_places");
  const [discoverMessage, setDiscoverMessage] = useState<string | null>(null);

  // Manual Form
  const [manualForm, setManualForm] = useState({
    company_name: "",
    website_url: "",
    phone: "",
    address: "",
    industry: "",
    notes: "",
  });

  const fetchLeads = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.leads.list({
        page: 1,
        page_size: 100,
        status: activeTab === "all" ? undefined : activeTab,
        search: searchQuery || undefined,
        min_score: minScore > 0 ? minScore : undefined,
      });
      setLeads(res.items);
    } catch (err: unknown) {
      const msg = err && typeof err === "object" && "detail" in err
        ? String((err as { detail: unknown }).detail)
        : "Failed to load leads";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLeads();
  }, [activeTab, minScore]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchLeads();
  };

  // Actions
  const handleApprove = async (leadId: string) => {
    setActionLoading(leadId);
    try {
      const updated = await api.leads.approve(leadId);
      setLeads((prev) => prev.map((l) => (l.id === leadId ? updated : l)));
      if (selectedLead?.id === leadId) setSelectedLead(updated);
    } catch (err: unknown) {
      alert("Failed to approve lead");
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async (leadId: string) => {
    const reason = prompt("Optional reason for rejecting this lead:") ?? undefined;
    setActionLoading(leadId);
    try {
      const updated = await api.leads.reject(leadId, reason);
      setLeads((prev) => prev.map((l) => (l.id === leadId ? updated : l)));
      if (selectedLead?.id === leadId) setSelectedLead(updated);
    } catch (err: unknown) {
      alert("Failed to reject lead");
    } finally {
      setActionLoading(null);
    }
  };

  const handleRequalify = async (leadId: string) => {
    setActionLoading(leadId);
    try {
      const updated = await api.leads.requalify(leadId);
      setLeads((prev) => prev.map((l) => (l.id === leadId ? updated : l)));
      if (selectedLead?.id === leadId) setSelectedLead(updated);
    } catch (err: unknown) {
      alert("Failed to re-qualify lead");
    } finally {
      setActionLoading(null);
    }
  };

  const handleTriggerDiscover = async (e: React.FormEvent) => {
    e.preventDefault();
    setDiscoverMessage(null);
    try {
      const run = await api.leads.discover({
        query: discoverQuery,
        location: discoverLocation || undefined,
        limit: Number(discoverLimit),
        provider: discoverProvider,
      });
      setDiscoverMessage(`Discovery job started (Run ID: ${run.id.slice(0, 8)}). Refreshing leads...`);
      setTimeout(() => {
        setShowDiscoverModal(false);
        setDiscoverMessage(null);
        fetchLeads();
      }, 1500);
    } catch (err: unknown) {
      const msg = err && typeof err === "object" && "detail" in err
        ? String((err as { detail: unknown }).detail)
        : "Failed to trigger discovery";
      setDiscoverMessage(`Error: ${msg}`);
    }
  };

  const handleCreateManual = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const newLead = await api.leads.createManual(manualForm);
      setLeads((prev) => [newLead, ...prev]);
      setShowManualModal(false);
      setManualForm({ company_name: "", website_url: "", phone: "", address: "", industry: "", notes: "" });
    } catch (err: unknown) {
      const msg = err && typeof err === "object" && "detail" in err
        ? String((err as { detail: unknown }).detail)
        : "Failed to create manual lead";
      alert(msg);
    }
  };

  // Status Counts
  const counts = useMemo(() => {
    const map: Record<string, number> = { all: leads.length };
    for (const l of leads) {
      map[l.status] = (map[l.status] || 0) + 1;
    }
    return map;
  }, [leads]);

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <span>Lead Pipeline</span>
            <span className="text-xs px-2.5 py-0.5 rounded-full font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              Phase 2 Active
            </span>
          </h2>
          <p className="text-sm text-neutral-400 mt-1">
            Objective technical audits, public business contacts, and deterministic qualification scoring.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setShowManualModal(true)}
            className="px-3.5 py-2 text-sm font-medium rounded-lg border border-neutral-700 hover:bg-neutral-800 text-neutral-300 transition-colors flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            <span>Add Manual Lead</span>
          </button>
          <button
            onClick={() => setShowDiscoverModal(true)}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white transition-colors shadow-lg shadow-emerald-950/30 flex items-center gap-2"
          >
            <Sparkles className="w-4 h-4" />
            <span>Discover Leads</span>
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl border border-neutral-800 bg-neutral-900/60 backdrop-blur-sm">
          <p className="text-xs font-medium text-neutral-400 uppercase tracking-wider">Total Leads</p>
          <p className="text-2xl font-bold text-white mt-1">{leads.length}</p>
        </div>
        <div className="p-4 rounded-xl border border-emerald-500/20 bg-emerald-950/10 backdrop-blur-sm">
          <p className="text-xs font-medium text-emerald-400 uppercase tracking-wider">Qualified (Score ≥ 60)</p>
          <p className="text-2xl font-bold text-emerald-300 mt-1">
            {leads.filter((l) => l.qualification_score >= 60).length}
          </p>
        </div>
        <div className="p-4 rounded-xl border border-blue-500/20 bg-blue-950/10 backdrop-blur-sm">
          <p className="text-xs font-medium text-blue-400 uppercase tracking-wider">Approved by Owner</p>
          <p className="text-2xl font-bold text-blue-300 mt-1">
            {leads.filter((l) => l.status === "approved").length}
          </p>
        </div>
        <div className="p-4 rounded-xl border border-neutral-800 bg-neutral-900/60 backdrop-blur-sm">
          <p className="text-xs font-medium text-neutral-400 uppercase tracking-wider">Public Contacts Found</p>
          <p className="text-2xl font-bold text-neutral-200 mt-1">
            {leads.filter((l) => l.email || l.phone).length}
          </p>
        </div>
      </div>

      {/* Filters & Pipeline Tabs */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-neutral-800 pb-3">
        {/* Status Tabs */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
          {[
            { id: "all", label: "All" },
            { id: "qualified", label: "Qualified" },
            { id: "approved", label: "Approved" },
            { id: "researched", label: "Researched" },
            { id: "discovered", label: "Discovered" },
            { id: "disqualified", label: "Disqualified" },
            { id: "rejected", label: "Rejected" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg whitespace-nowrap transition-colors flex items-center gap-1.5 ${
                activeTab === tab.id
                  ? "bg-neutral-800 text-white shadow-sm"
                  : "text-neutral-400 hover:text-neutral-200 hover:bg-neutral-900"
              }`}
            >
              <span>{tab.label}</span>
              {counts[tab.id] !== undefined && (
                <span className={`px-1.5 py-0.2 rounded-full text-[10px] ${activeTab === tab.id ? "bg-neutral-700 text-white" : "bg-neutral-800 text-neutral-400"}`}>
                  {counts[tab.id]}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Search & Score Slider */}
        <form onSubmit={handleSearchSubmit} className="flex items-center gap-2.5">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
            <input
              type="text"
              placeholder="Search company or domain..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 pr-3 py-1.5 text-xs rounded-lg bg-neutral-900 border border-neutral-800 text-neutral-200 placeholder-neutral-500 focus:outline-none focus:border-neutral-600 w-56"
            />
          </div>
          <div className="flex items-center gap-2 text-xs text-neutral-400">
            <span>Score ≥</span>
            <input
              type="number"
              min="0"
              max="100"
              value={minScore || ""}
              onChange={(e) => setMinScore(Number(e.target.value))}
              placeholder="0"
              className="w-14 px-2 py-1.5 text-xs rounded-lg bg-neutral-900 border border-neutral-800 text-neutral-200 focus:outline-none focus:border-neutral-600"
            />
          </div>
          <button type="submit" className="p-1.5 rounded-lg border border-neutral-800 hover:bg-neutral-800 text-neutral-300">
            <Filter className="w-3.5 h-3.5" />
          </button>
        </form>
      </div>

      {/* Main Table */}
      <div className="rounded-xl border border-neutral-800 bg-neutral-900/40 overflow-hidden shadow-xl">
        {loading ? (
          <div className="py-20 text-center text-neutral-500 text-sm">Loading lead pipeline...</div>
        ) : error ? (
          <div className="py-16 text-center text-red-400 text-sm">{error}</div>
        ) : leads.length === 0 ? (
          <div className="py-20 flex flex-col items-center justify-center text-center text-neutral-500">
            <Building className="w-8 h-8 text-neutral-600 mb-2" />
            <p className="text-sm font-medium text-neutral-300">No leads found in this view</p>
            <p className="text-xs text-neutral-500 mt-1 max-w-sm">
              Trigger lead research with Google Places or input target websites manually to start building your pipeline.
            </p>
            <button
              onClick={() => setShowDiscoverModal(true)}
              className="mt-4 px-3.5 py-1.5 text-xs font-medium rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white transition-colors"
            >
              ＋ Discover Leads
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-neutral-300">
              <thead className="bg-neutral-900/90 text-neutral-400 uppercase tracking-wider text-[10px] border-b border-neutral-800 font-semibold">
                <tr>
                  <th className="py-3 px-4">Company & Website</th>
                  <th className="py-3 px-3">Opportunity Score</th>
                  <th className="py-3 px-3">Objective Findings</th>
                  <th className="py-3 px-3">Public Contact</th>
                  <th className="py-3 px-3">Status</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800/60 font-normal">
                {leads.map((lead) => {
                  const r = lead.research;
                  return (
                    <tr key={lead.id} className="hover:bg-neutral-800/40 transition-colors">
                      {/* Company & Domain */}
                      <td className="py-3 px-4">
                        <div className="font-medium text-white text-sm">{lead.company_name}</div>
                        <div className="flex items-center gap-2 mt-0.5">
                          {lead.website_url ? (
                            <a
                              href={lead.website_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-xs text-emerald-400 hover:underline flex items-center gap-1 font-mono"
                            >
                              <span>{lead.domain}</span>
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          ) : (
                            <span className="text-xs text-neutral-500 italic">No website URL</span>
                          )}
                          {lead.industry && (
                            <span className="text-[10px] text-neutral-400 bg-neutral-800/80 px-1.5 py-0.5 rounded">
                              {lead.industry}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Score Badge */}
                      <td className="py-3 px-3">
                        <div className="flex items-center gap-2">
                          <span
                            className={`px-2.5 py-1 rounded-md font-mono text-xs font-semibold ${
                              lead.qualification_score >= 60
                                ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                                : lead.qualification_score >= 30
                                ? "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                                : "bg-neutral-800 text-neutral-400 border border-neutral-700"
                            }`}
                          >
                            {lead.qualification_score} / 100
                          </span>
                        </div>
                      </td>

                      {/* Technical Findings Badges */}
                      <td className="py-3 px-3">
                        <div className="flex flex-wrap gap-1 max-w-xs">
                          {r && !r.has_website && (
                            <span className="px-1.5 py-0.5 rounded bg-red-950/40 text-red-400 border border-red-800/50 text-[10px]">
                              No Website
                            </span>
                          )}
                          {r && r.has_ssl === false && (
                            <span className="px-1.5 py-0.5 rounded bg-amber-950/40 text-amber-300 border border-amber-800/50 text-[10px]">
                              Insecure (No SSL)
                            </span>
                          )}
                          {r && r.is_responsive === false && (
                            <span className="px-1.5 py-0.5 rounded bg-orange-950/40 text-orange-300 border border-orange-800/50 text-[10px]">
                              Not Mobile
                            </span>
                          )}
                          {r && r.copyright_year && r.copyright_year <= 2022 && (
                            <span className="px-1.5 py-0.5 rounded bg-blue-950/40 text-blue-300 border border-blue-800/50 text-[10px]">
                              © {r.copyright_year}
                            </span>
                          )}
                          {r && r.load_time_ms && r.load_time_ms > 2500 && (
                            <span className="px-1.5 py-0.5 rounded bg-yellow-950/40 text-yellow-300 border border-yellow-800/50 text-[10px]">
                              Slow ({r.load_time_ms}ms)
                            </span>
                          )}
                          {r && r.is_responsive && r.has_ssl && (
                            <span className="px-1.5 py-0.5 rounded bg-emerald-950/40 text-emerald-400 border border-emerald-800/50 text-[10px]">
                              Modern
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Contact Info */}
                      <td className="py-3 px-3">
                        <div className="space-y-1">
                          {lead.email ? (
                            <div className="flex items-center gap-1.5 text-neutral-300">
                              <Mail className="w-3 h-3 text-neutral-400" />
                              <span className="font-mono text-[11px] truncate max-w-[140px]">{lead.email}</span>
                              <span
                                className={`text-[9px] px-1 py-0.2 rounded font-mono ${
                                  lead.email_verification_status === "mx_verified"
                                    ? "bg-emerald-900/40 text-emerald-300"
                                    : "bg-neutral-800 text-neutral-400"
                                }`}
                              >
                                {lead.email_verification_status === "mx_verified" ? "MX" : "Syntax"}
                              </span>
                            </div>
                          ) : (
                            <span className="text-[11px] text-neutral-500 italic">No email</span>
                          )}
                          {lead.phone && (
                            <div className="flex items-center gap-1.5 text-neutral-400 text-[11px]">
                              <Phone className="w-3 h-3 text-neutral-500" />
                              <span>{lead.phone}</span>
                            </div>
                          )}
                        </div>
                      </td>

                      {/* Status */}
                      <td className="py-3 px-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[11px] font-medium capitalize ${
                            lead.status === "approved"
                              ? "bg-blue-500/20 text-blue-300 border border-blue-500/30"
                              : lead.status === "qualified"
                              ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                              : lead.status === "rejected"
                              ? "bg-red-500/20 text-red-300 border border-red-500/30"
                              : lead.status === "disqualified"
                              ? "bg-neutral-800 text-neutral-400 border border-neutral-700"
                              : "bg-neutral-800 text-neutral-300 border border-neutral-700"
                          }`}
                        >
                          {lead.status}
                        </span>
                      </td>

                      {/* Actions */}
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => setSelectedLead(lead)}
                            className="px-2.5 py-1 text-xs rounded border border-neutral-700 hover:bg-neutral-800 text-neutral-300"
                          >
                            Audit
                          </button>
                          {lead.status !== "approved" && (
                            <button
                              onClick={() => handleApprove(lead.id)}
                              disabled={actionLoading === lead.id}
                              className="px-2.5 py-1 text-xs rounded bg-blue-600/80 hover:bg-blue-600 text-white font-medium disabled:opacity-50"
                            >
                              Approve
                            </button>
                          )}
                          {lead.status !== "rejected" && (
                            <button
                              onClick={() => handleReject(lead.id)}
                              disabled={actionLoading === lead.id}
                              className="px-2 py-1 text-xs rounded border border-red-900/60 hover:bg-red-950/40 text-red-400 disabled:opacity-50"
                            >
                              Reject
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Slide-over / Modal: Audit Findings & Provenance ──────────────────── */}
      {selectedLead && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-end">
          <div className="w-full max-w-xl h-full bg-neutral-900 border-l border-neutral-800 p-6 overflow-y-auto space-y-6">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-lg font-bold text-white">{selectedLead.company_name}</h3>
                <p className="text-xs text-neutral-400 font-mono mt-0.5">{selectedLead.domain}</p>
              </div>
              <button
                onClick={() => setSelectedLead(null)}
                className="p-1.5 rounded-lg border border-neutral-800 text-neutral-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Score & Summary */}
            <div className="p-4 rounded-xl border border-neutral-800 bg-neutral-950/60 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-neutral-400">Opportunity Score</span>
                <span className="text-lg font-bold font-mono text-emerald-400">
                  {selectedLead.qualification_score} / 100
                </span>
              </div>
              <div className="w-full bg-neutral-800 h-2 rounded-full overflow-hidden">
                <div
                  className="bg-emerald-500 h-full rounded-full"
                  style={{ width: `${selectedLead.qualification_score}%` }}
                />
              </div>
              <p className="text-xs text-neutral-300">
                {selectedLead.research?.research_notes || "Deterministic analysis completed."}
              </p>
            </div>

            {/* Observable Technical Findings */}
            <div className="space-y-3">
              <h4 className="text-xs font-semibold text-neutral-300 uppercase tracking-wider">
                Verifiable Technical Findings
              </h4>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-3 rounded-lg border border-neutral-800 bg-neutral-950/40">
                  <span className="text-neutral-500">Mobile Responsive</span>
                  <p className="font-medium mt-1 text-white">
                    {selectedLead.research?.is_responsive ? "✅ Yes" : "❌ No Viewport"}
                  </p>
                </div>
                <div className="p-3 rounded-lg border border-neutral-800 bg-neutral-950/40">
                  <span className="text-neutral-500">SSL / HTTPS</span>
                  <p className="font-medium mt-1 text-white">
                    {selectedLead.research?.has_ssl ? "✅ Enabled" : "❌ Insecure HTTP"}
                  </p>
                </div>
                <div className="p-3 rounded-lg border border-neutral-800 bg-neutral-950/40">
                  <span className="text-neutral-500">Response Latency</span>
                  <p className="font-medium mt-1 text-white">
                    {selectedLead.research?.load_time_ms ? `${selectedLead.research.load_time_ms}ms` : "N/A"}
                  </p>
                </div>
                <div className="p-3 rounded-lg border border-neutral-800 bg-neutral-950/40">
                  <span className="text-neutral-500">Copyright Recency</span>
                  <p className="font-medium mt-1 text-white">
                    {selectedLead.research?.copyright_year ? `© ${selectedLead.research.copyright_year}` : "Undetected"}
                  </p>
                </div>
              </div>

              {selectedLead.research?.audit_findings?.findings && (
                <ul className="mt-2 space-y-1 text-xs text-neutral-300">
                  {selectedLead.research.audit_findings.findings.map((f, i) => (
                    <li key={i} className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Public Contact Information */}
            <div className="space-y-3">
              <h4 className="text-xs font-semibold text-neutral-300 uppercase tracking-wider">
                Public Business Contacts
              </h4>
              <div className="p-3 rounded-lg border border-neutral-800 bg-neutral-950/40 space-y-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-neutral-400">Email</span>
                  <span className="font-mono text-white">{selectedLead.email || "None discovered"}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-neutral-400">Verification</span>
                  <span className="text-[11px] font-mono text-emerald-400 uppercase">
                    {selectedLead.email_verification_status}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-neutral-400">Phone</span>
                  <span className="text-white">{selectedLead.phone || "None discovered"}</span>
                </div>
                {selectedLead.address && (
                  <div className="flex items-center justify-between">
                    <span className="text-neutral-400">Address</span>
                    <span className="text-white text-right max-w-xs">{selectedLead.address}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Source Provenance */}
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-neutral-300 uppercase tracking-wider">
                Source Provenance
              </h4>
              <div className="p-3 rounded-lg border border-neutral-800 bg-neutral-950/40 text-xs space-y-1 font-mono text-neutral-400">
                <p>Provider: {selectedLead.source_type}</p>
                {selectedLead.source_query && <p>Query: {selectedLead.source_query}</p>}
                {selectedLead.source_url && (
                  <p className="truncate">Source URL: {selectedLead.source_url}</p>
                )}
                <p>Discovered: {new Date(selectedLead.created_at).toLocaleString()}</p>
              </div>
            </div>

            {/* Drawer Actions */}
            <div className="pt-4 border-t border-neutral-800 flex items-center justify-between">
              <button
                onClick={() => handleRequalify(selectedLead.id)}
                disabled={actionLoading === selectedLead.id}
                className="px-3 py-1.5 text-xs rounded border border-neutral-700 hover:bg-neutral-800 text-neutral-300 flex items-center gap-1.5"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Re-Audit Lead</span>
              </button>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleReject(selectedLead.id)}
                  disabled={actionLoading === selectedLead.id}
                  className="px-3 py-1.5 text-xs rounded border border-red-900/60 hover:bg-red-950/40 text-red-400 font-medium"
                >
                  Reject
                </button>
                <button
                  onClick={() => handleApprove(selectedLead.id)}
                  disabled={actionLoading === selectedLead.id}
                  className="px-4 py-1.5 text-xs rounded bg-blue-600 hover:bg-blue-500 text-white font-medium"
                >
                  Approve for Outreach
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Modal: Discover Leads ───────────────────────────────────────────── */}
      {showDiscoverModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md bg-neutral-900 border border-neutral-800 rounded-xl p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-emerald-400" />
                <span>Discover Leads</span>
              </h3>
              <button onClick={() => setShowDiscoverModal(false)} className="text-neutral-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleTriggerDiscover} className="space-y-3.5 text-xs">
              <div>
                <label className="block text-neutral-300 mb-1">Target Niche or Business Type</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. plumbers, roofing contractors, dentists"
                  value={discoverQuery}
                  onChange={(e) => setDiscoverQuery(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-neutral-950 border border-neutral-800 text-white focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div>
                <label className="block text-neutral-300 mb-1">Location / Market</label>
                <input
                  type="text"
                  placeholder="e.g. Austin, TX or Phoenix, AZ"
                  value={discoverLocation}
                  onChange={(e) => setDiscoverLocation(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-neutral-950 border border-neutral-800 text-white focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-neutral-300 mb-1">Provider</label>
                  <select
                    value={discoverProvider}
                    onChange={(e) => setDiscoverProvider(e.target.value)}
                    className="w-full px-2.5 py-2 rounded-lg bg-neutral-950 border border-neutral-800 text-white focus:outline-none focus:border-emerald-500"
                  >
                    <option value="google_places">Google Places API</option>
                    <option value="manual_entry">Manual Entry</option>
                  </select>
                </div>
                <div>
                  <label className="block text-neutral-300 mb-1">Batch Limit (Max 20)</label>
                  <input
                    type="number"
                    min="1"
                    max="20"
                    value={discoverLimit}
                    onChange={(e) => setDiscoverLimit(Number(e.target.value))}
                    className="w-full px-3 py-2 rounded-lg bg-neutral-950 border border-neutral-800 text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
              </div>

              {discoverMessage && (
                <p className="text-xs p-2 rounded bg-neutral-800 text-emerald-300">{discoverMessage}</p>
              )}

              <div className="pt-2 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowDiscoverModal(false)}
                  className="px-3 py-1.5 rounded border border-neutral-800 text-neutral-300 hover:bg-neutral-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium"
                >
                  Run Research Agent
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Modal: Add Manual Lead ─────────────────────────────────────────── */}
      {showManualModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md bg-neutral-900 border border-neutral-800 rounded-xl p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Plus className="w-4 h-4 text-emerald-400" />
                <span>Add Lead Manually</span>
              </h3>
              <button onClick={() => setShowManualModal(false)} className="text-neutral-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateManual} className="space-y-3 text-xs">
              <div>
                <label className="block text-neutral-300 mb-1">Company Name *</label>
                <input
                  type="text"
                  required
                  placeholder="Acme Plumbing"
                  value={manualForm.company_name}
                  onChange={(e) => setManualForm({ ...manualForm, company_name: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-neutral-950 border border-neutral-800 text-white focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div>
                <label className="block text-neutral-300 mb-1">Website URL</label>
                <input
                  type="text"
                  placeholder="https://www.acmeplumbing.com"
                  value={manualForm.website_url}
                  onChange={(e) => setManualForm({ ...manualForm, website_url: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-neutral-950 border border-neutral-800 text-white focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-neutral-300 mb-1">Phone</label>
                  <input
                    type="text"
                    placeholder="(512) 555-1234"
                    value={manualForm.phone}
                    onChange={(e) => setManualForm({ ...manualForm, phone: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-neutral-950 border border-neutral-800 text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div>
                  <label className="block text-neutral-300 mb-1">Industry</label>
                  <input
                    type="text"
                    placeholder="Plumbing"
                    value={manualForm.industry}
                    onChange={(e) => setManualForm({ ...manualForm, industry: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-neutral-950 border border-neutral-800 text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-neutral-300 mb-1">Address / City</label>
                <input
                  type="text"
                  placeholder="Austin, TX"
                  value={manualForm.address}
                  onChange={(e) => setManualForm({ ...manualForm, address: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-neutral-950 border border-neutral-800 text-white focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowManualModal(false)}
                  className="px-3 py-1.5 rounded border border-neutral-800 text-neutral-300 hover:bg-neutral-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium"
                >
                  Audit & Save Lead
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
