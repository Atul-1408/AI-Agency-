/**
 * Phase 1 Dashboard API Client.
 *
 * All API calls go through this module.
 * No component imports fetch() directly.
 *
 * Authentication:
 *   Token is stored in localStorage (Phase 1 — httpOnly cookie in Phase 2).
 *   All authenticated calls automatically attach the Bearer header.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Token management ──────────────────────────────────────────────────────────

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
    const token = getToken();
    if (!token) {
      throw { detail: "Not authenticated", status: 401 } as ApiError;
    }
    headers["Authorization"] = `Bearer ${token}`;
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

// ── Types ─────────────────────────────────────────────────────────────────────

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

// ── API calls ─────────────────────────────────────────────────────────────────

export const api = {
  // Health — no auth required
  health: () =>
    apiFetch<HealthResponse>("/api/v1/health", {}, false),

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

  // Agent registry — no auth required
  agents: {
    registry: () =>
      apiFetch<{ agents: Record<string, AgentRegistryEntry>; phase_1_active: string[] }>(
        "/api/v1/agents/registry",
        {},
        false
      ),

    // Runs — auth required
    listRuns: (params?: { page?: number; page_size?: number; agent_name?: string; status?: string }) => {
      const qs = new URLSearchParams(
        Object.entries(params ?? {})
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, String(v)])
      ).toString();
      return apiFetch<PaginatedResponse<AgentRun>>(`/api/v1/agents/runs${qs ? `?${qs}` : ""}`);
    },

    getRun: (id: string) =>
      apiFetch<AgentRun>(`/api/v1/agents/runs/${id}`),

    trigger: (agentName: string, inputData?: Record<string, unknown>) =>
      apiFetch<AgentRun>("/api/v1/agents/trigger", {
        method: "POST",
        body: JSON.stringify({ agent_name: agentName, input_data: inputData }),
      }),

    // Approvals — auth required
    listApprovals: (status?: string) =>
      apiFetch<PaginatedResponse<ApprovalRequest>>(
        `/api/v1/agents/approvals${status ? `?status=${status}` : ""}`
      ),

    decide: (id: string, decision: "approved" | "rejected", note?: string) =>
      apiFetch<ApprovalRequest>(`/api/v1/agents/approvals/${id}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision, owner_note: note ?? null }),
      }),
  },
};
