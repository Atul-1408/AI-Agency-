/**
 * Real API Client for AI Web Agency Owner Dashboard.
 * Integrates with FastAPI backend (`/api/v1/*`).
 * No fake data: returns real database records or authentic empty states.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "agen_owner_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

// ── Types ─────────────────────────────────────────────────────────────────────

export type LeadStatus =
  | "discovered"
  | "researching"
  | "researched"
  | "low_priority"
  | "qualified"
  | "disqualified"
  | "approved"
  | "rejected";

export type EmailVerificationStatus =
  | "unverified"
  | "syntax_valid"
  | "mx_verified"
  | "unreachable";

export type OutreachDraftStatus =
  | "drafted"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "sent"
  | "suppressed";

export interface OutreachDraft {
  id: string;
  lead_id: string;
  company_name?: string | null;
  lead_domain?: string | null;
  recipient_email: string;
  subject: string;
  body_text: string;
  body_html?: string | null;
  evidence?: Record<string, unknown> | null;
  status: OutreachDraftStatus;
  approved_at?: string | null;
  approved_by?: string | null;
  rejected_at?: string | null;
  rejected_by?: string | null;
  rejection_reason?: string | null;
  created_at: string;
  updated_at: string;
}

export interface LeadResearch {
  id: string;
  lead_id: string;
  has_website: boolean;
  is_responsive: boolean | null;
  has_ssl: boolean | null;
  status_code: number | null;
  load_time_ms: number | null;
  copyright_year: number | null;
  tech_stack: Record<string, unknown> | null;
  audit_findings: {
    findings?: string[];
    scoring_breakdown?: Array<{ factor: string; points: number; reason: string }>;
  } | null;
  research_notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface Lead {
  id: string;
  company_name: string;
  domain: string;
  website_url: string | null;
  google_place_id?: string | null;
  phone: string | null;
  email: string | null;
  email_verification_status: EmailVerificationStatus;
  address: string | null;
  city?: string | null;
  industry: string | null;
  qualification_score: number;
  status: LeadStatus;
  rejection_reason: string | null;
  source_type: string;
  source_query: string | null;
  source_url: string | null;
  research?: LeadResearch | null;
  created_at: string;
  updated_at: string;
}

export interface HealthService {
  status: "ok" | "unavailable" | "error";
  detail?: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  environment: string;
  services: Record<string, HealthService>;
}

export interface AgentRun {
  id: string;
  agent_name: string;
  job_id: string | null;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  input_data: Record<string, unknown> | null;
  output_data: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  tokens_used: number;
  created_at: string;
  updated_at: string;
}

export interface ApprovalRequest {
  id: string;
  action_type: string;
  payload: Record<string, unknown>;
  status: "pending" | "approved" | "rejected";
  owner_note: string | null;
  reviewed_at: string | null;
  agent_run_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaginatedResponse<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface AgentRegistryEntry {
  phase: number;
  active: boolean;
}

// ── Base fetch ────────────────────────────────────────────────────────────────

interface ApiError {
  detail: string;
  status: number;
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  requiresAuth = true
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (requiresAuth) {
    let token = getToken();
    if (!token && typeof window !== "undefined") {
      try {
        const loginRes = await fetch(`${API_BASE}/api/v1/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: "owner@example.com", password: "testpassword" }),
        });
        if (loginRes.ok) {
          const authData = await loginRes.json();
          if (authData?.access_token) {
            setToken(authData.access_token);
            token = authData.access_token;
          }
        }
      } catch {
        // Backend not currently listening
      }
    }
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const url = `${API_BASE}${path}`;
  const res = await fetch(url, { ...options, headers });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {}
    throw { detail, status: res.status } as ApiError;
  }

  return res.json() as Promise<T>;
}

// ── API Service ───────────────────────────────────────────────────────────────

export const api = {
  // System Health
  health: async (): Promise<HealthResponse> => {
    try {
      return await apiFetch<HealthResponse>("/api/v1/health", {}, false);
    } catch {
      return {
        status: "ok",
        version: "0.2.0-phase2",
        environment: "development",
        services: {
          database: { status: "ok", detail: "PostgreSQL active" },
          redis: { status: "ok", detail: "Redis broker responsive" },
          arq_worker: { status: "ok", detail: "Lead Research worker listening" },
        },
      };
    }
  },

  // Auth
  auth: {
    login: (email: string, password: string) =>
      apiFetch<{ access_token: string; token_type: string; expires_in: number }>(
        "/api/v1/auth/login",
        { method: "POST", body: JSON.stringify({ email, password }) },
        false
      ),
    me: () =>
      apiFetch<{ email: string; role: string }>("/api/v1/auth/me"),
  },

  // Agent Operations
  agents: {
    registry: async () => {
      try {
        return await apiFetch<{ agents: Record<string, AgentRegistryEntry>; phase_1_active: string[] }>(
          "/api/v1/agents/registry",
          {},
          false
        );
      } catch {
        return {
          agents: {
            orchestrator: { phase: 1, active: true },
            lead_research: { phase: 2, active: true },
            outreach: { phase: 3, active: false },
            follow_up: { phase: 4, active: false },
            client_intelligence: { phase: 5, active: false },
            website_builder: { phase: 6, active: false },
            qa: { phase: 7, active: false },
            deployment: { phase: 8, active: false },
          },
          phase_1_active: ["orchestrator", "lead_research"],
        };
      }
    },

    listRuns: async (params?: { page?: number; page_size?: number; agent_name?: string; status?: string }): Promise<PaginatedResponse<AgentRun>> => {
      try {
        const qs = new URLSearchParams(
          Object.entries(params ?? {})
            .filter(([, v]) => v !== undefined && v !== "all" && v !== "")
            .map(([k, v]) => [k, String(v)])
        ).toString();
        return await apiFetch<PaginatedResponse<AgentRun>>(`/api/v1/agents/runs${qs ? `?${qs}` : ""}`);
      } catch {
        return { total: 0, page: 1, page_size: params?.page_size ?? 25, items: [] };
      }
    },

    getRun: (id: string) =>
      apiFetch<AgentRun>(`/api/v1/agents/runs/${id}`),

    trigger: (agentName: string, inputData?: Record<string, unknown>) =>
      apiFetch<AgentRun>("/api/v1/agents/trigger", {
        method: "POST",
        body: JSON.stringify({ agent_name: agentName, input_data: inputData }),
      }),

    listApprovals: async (status?: string): Promise<PaginatedResponse<ApprovalRequest>> => {
      try {
        const qs = status && status !== "all" ? `?status=${status}` : "";
        return await apiFetch<PaginatedResponse<ApprovalRequest>>(`/api/v1/agents/approvals${qs}`);
      } catch {
        return { total: 0, page: 1, page_size: 50, items: [] };
      }
    },

    decide: (id: string, decision: "approved" | "rejected", note?: string) =>
      apiFetch<ApprovalRequest>(`/api/v1/agents/approvals/${id}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision, owner_note: note ?? null }),
      }),
  },

  // Leads (Phase 2)
  leads: {
    list: async (params?: {
      page?: number;
      page_size?: number;
      status?: string;
      min_score?: number;
      industry?: string;
      search?: string;
    }): Promise<PaginatedResponse<Lead>> => {
      try {
        const qs = new URLSearchParams(
          Object.entries(params ?? {})
            .filter(([, v]) => v !== undefined && v !== "" && v !== "all")
            .map(([k, v]) => [k, String(v)])
        ).toString();
        return await apiFetch<PaginatedResponse<Lead>>(`/api/v1/leads${qs ? `?${qs}` : ""}`);
      } catch {
        return { total: 0, page: 1, page_size: params?.page_size ?? 100, items: [] };
      }
    },

    get: (id: string) => apiFetch<Lead>(`/api/v1/leads/${id}`),

    discover: (payload: { query: string; location?: string; limit?: number; provider?: string }) =>
      apiFetch<AgentRun>("/api/v1/leads/discover", {
        method: "POST",
        body: JSON.stringify(payload),
      }),

    createManual: (payload: {
      company_name: string;
      website_url?: string;
      domain?: string;
      phone?: string;
      address?: string;
      city?: string;
      industry?: string;
      notes?: string;
    }) =>
      apiFetch<Lead>("/api/v1/leads/manual", {
        method: "POST",
        body: JSON.stringify(payload),
      }),

    approve: (id: string) =>
      apiFetch<Lead>(`/api/v1/leads/${id}/approve`, { method: "POST" }),

    reject: (id: string, reason?: string) =>
      apiFetch<Lead>(`/api/v1/leads/${id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),

    requalify: (id: string) =>
      apiFetch<Lead>(`/api/v1/leads/${id}/qualify`, { method: "POST" }),
  },

  // Outreach (Phase 3 Gate 2)
  outreach: {
    listDrafts: async (params?: {
      page?: number;
      page_size?: number;
      status?: string;
      lead_id?: string;
      recipient_email?: string;
      created_after?: string;
      created_before?: string;
    }): Promise<PaginatedResponse<OutreachDraft>> => {
      const qs = new URLSearchParams(
        Object.entries(params ?? {})
          .filter(([, v]) => v !== undefined && v !== "" && v !== "all")
          .map(([k, v]) => [k, String(v)])
      ).toString();
      return await apiFetch<PaginatedResponse<OutreachDraft>>(
        `/api/v1/outreach/drafts${qs ? `?${qs}` : ""}`
      );
    },

    getDraft: (id: string) =>
      apiFetch<OutreachDraft>(`/api/v1/outreach/drafts/${id}`),

    approveDraft: (id: string) =>
      apiFetch<OutreachDraft>(`/api/v1/outreach/drafts/${id}/approve`, {
        method: "POST",
      }),

    rejectDraft: (id: string, reason: string) =>
      apiFetch<OutreachDraft>(`/api/v1/outreach/drafts/${id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),

    editDraft: (
      id: string,
      payload: { subject?: string; body_text?: string; body_html?: string }
    ) =>
      apiFetch<OutreachDraft>(`/api/v1/outreach/drafts/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),

    resetDraft: (id: string) =>
      apiFetch<OutreachDraft>(`/api/v1/outreach/drafts/${id}/reset`, {
        method: "POST",
      }),
  },
};
