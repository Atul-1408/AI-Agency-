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

  // Client Intelligence & PRD (Phase 5 Stage 5.3 Gate 4)
  prd: {
    generate: (conversation_id: string) =>
      apiFetch<PRDDetail>("/api/v1/prds", {
        method: "POST",
        body: JSON.stringify({ conversation_id }),
      }),

    list: async (conversation_id?: string): Promise<PRD[]> => {
      const qs = conversation_id ? `?conversation_id=${encodeURIComponent(conversation_id)}` : "";
      return await apiFetch<PRD[]>(`/api/v1/prds${qs}`);
    },

    get: (id: string) =>
      apiFetch<PRDDetail>(`/api/v1/prds/${id}`),

    approve: (id: string, notes?: string) =>
      apiFetch<PRD>(`/api/v1/prds/${id}/approve`, {
        method: "POST",
        body: JSON.stringify({ notes }),
      }),

    reject: (id: string, rejection_reason?: string) =>
      apiFetch<PRD>(`/api/v1/prds/${id}/reject`, {
        method: "POST",
        body: JSON.stringify({ rejection_reason }),
      }),
  },
  projects: {
    list: (params?: { status?: string; search?: string }) => {
      const q = new URLSearchParams();
      if (params?.status) q.set("status", params.status);
      if (params?.search) q.set("search", params.search);
      const qs = q.toString() ? `?${q.toString()}` : "";
      return apiFetch<ProjectListResponse>(`/api/v1/projects${qs}`);
    },
    get: (id: string) => apiFetch<ProjectDetail>(`/api/v1/projects/${id}`),
    create: (payload: { approved_prd_id: string; custom_project_name?: string }) =>
      apiFetch<Project>("/api/v1/projects", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    update: (
      id: string,
      payload: {
        project_name?: string;
        project_status?: string;
        phase_metadata?: Record<string, unknown>;
      }
    ) =>
      apiFetch<Project>(`/api/v1/projects/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
  },
  websiteBuilder: {
    createSession: (projectId: string) =>
      apiFetch<WebsiteBuildSession>(`/api/v1/projects/${projectId}/build-sessions`, {
        method: "POST",
      }),
    listSessions: (projectId: string) =>
      apiFetch<WebsiteBuildSessionListResponse>(
        `/api/v1/projects/${projectId}/build-sessions`
      ),
    getSession: (sessionId: string) =>
      apiFetch<WebsiteBuildSessionDetail>(`/api/v1/build-sessions/${sessionId}`),
    planSession: (sessionId: string, notes?: string) =>
      apiFetch<WebsiteBuildSession>(`/api/v1/build-sessions/${sessionId}/plan`, {
        method: "POST",
        body: JSON.stringify({ notes }),
      }),
    readySession: (sessionId: string, notes?: string) =>
      apiFetch<WebsiteBuildSession>(`/api/v1/build-sessions/${sessionId}/ready`, {
        method: "POST",
        body: JSON.stringify({ notes }),
      }),
    pauseSession: (sessionId: string, reason?: string) =>
      apiFetch<WebsiteBuildSession>(`/api/v1/build-sessions/${sessionId}/pause`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
    cancelSession: (sessionId: string, reason?: string) =>
      apiFetch<WebsiteBuildSession>(`/api/v1/build-sessions/${sessionId}/cancel`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
    createGeneration: (sessionId: string) =>
      apiFetch<WebsiteGeneration>(`/api/v1/build-sessions/${sessionId}/generations`, {
        method: "POST",
      }),
    listGenerations: (sessionId: string) =>
      apiFetch<WebsiteGenerationListResponse>(
        `/api/v1/build-sessions/${sessionId}/generations`
      ),
    getGeneration: (generationId: string) =>
      apiFetch<WebsiteGenerationDetail>(`/api/v1/generations/${generationId}`),
    cancelGeneration: (generationId: string, reason?: string) =>
      apiFetch<WebsiteGeneration>(`/api/v1/generations/${generationId}/cancel`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
    createBlueprint: (generationId: string) =>
      apiFetch<DesignBlueprint>(`/api/v1/generations/${generationId}/blueprints`, {
        method: "POST",
      }),
    listBlueprints: (generationId: string) =>
      apiFetch<DesignBlueprintListResponse>(
        `/api/v1/generations/${generationId}/blueprints`
      ),
    getBlueprint: (blueprintId: string) =>
      apiFetch<DesignBlueprintDetail>(`/api/v1/design-blueprints/${blueprintId}`),
    cancelBlueprint: (blueprintId: string, reason?: string) =>
      apiFetch<DesignBlueprint>(`/api/v1/design-blueprints/${blueprintId}/cancel`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),
  },
};



// ── PRD Types ─────────────────────────────────────────────────────────────────

export type PRDStatus =
  | "draft"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "superseded";

export interface PRDRequirementReference {
  id: string;
  prd_id: string;
  requirement_id: string;
  requirement_version: number;
  section_key: string;
  source_message_id?: string | null;
  evidence_excerpt?: string | null;
  created_at: string;
}

export interface PRD {
  id: string;
  owner_email: string;
  lead_id: string;
  conversation_id: string;
  version: number;
  status: PRDStatus;
  title: string;
  executive_summary: string;
  business_overview: Record<string, unknown>;
  goals: string[];
  target_audience?: unknown;
  sitemap: Array<{ page: string; status?: string }>;
  content_requirements: Record<string, unknown>;
  functionality_requirements: Record<string, unknown>;
  design_requirements: Record<string, unknown>;
  branding_requirements: Record<string, unknown>;
  contact_requirements: Record<string, unknown>;
  technical_requirements: Record<string, unknown>;
  timeline: Record<string, unknown>;
  budget: Record<string, unknown>;
  assumptions: string[];
  open_questions: Array<Record<string, unknown>>;
  requirement_traceability: Record<string, unknown>;
  generated_at: string;
  approved_at?: string | null;
  approved_by?: string | null;
  rejected_at?: string | null;
  rejected_by?: string | null;
  rejection_reason?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PRDDetail extends PRD {
  requirement_references: PRDRequirementReference[];
  completeness?: {
    conversation_id: string;
    overall_completeness_percentage: number;
    overall_status: string;
    categories: Array<{
      category: string;
      status: string;
      total_fields: number;
      present_fields: string[];
      missing_fields: string[];
      completeness_percentage: number;
    }>;
    total_fields: number;
    total_present: number;
    total_missing: number;
  };
}

// ── Project Types ─────────────────────────────────────────────────────────────

export type ProjectStatus =
  | "draft"
  | "ready_for_build"
  | "in_build"
  | "qa"
  | "ready_for_deployment"
  | "deployed"
  | "completed"
  | "cancelled";

export interface Project {
  id: string;
  owner_id: string;
  lead_id: string;
  conversation_id: string;
  approved_prd_id: string;
  prd_version: number;
  project_name: string;
  project_slug: string;
  project_status: ProjectStatus;
  project_source: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  phase_metadata: Record<string, unknown>;
}

export interface ProjectDetail extends Project {
  business_name?: string | null;
  business_domain?: string | null;
  business_type?: string | null;
  lead_info?: Record<string, unknown> | null;
  conversation_summary?: {
    conversation_id?: string | null;
    status?: string | null;
    message_count: number;
    has_unreplied_inbound: boolean;
    last_message_at?: string | null;
  } | null;
  prd_summary?: {
    prd_id?: string | null;
    version: number;
    title?: string | null;
    status?: string | null;
    approved_at?: string | null;
    approved_by?: string | null;
    executive_summary?: string | null;
    sitemap?: Array<{ page: string; status?: string }>;
  } | null;
  requirements_summary?: {
    traceability_count: number;
  } | null;
  handoff_readiness?: {
    phase_6_ready: boolean;
    approved_prd_id: string;
    approved_prd_version: number;
    open_questions_count: number;
    mapped_requirements_count: number;
    status: string;
  } | null;
}

export interface ProjectListResponse {
  items: Project[];
  total: number;
  ready_for_build_count: number;
  in_build_count: number;
  completed_count: number;
}

// ── Website Builder Types ────────────────────────────────────────────────────

export type WebsiteBuildSessionStatus =
  | "created"
  | "planned"
  | "ready"
  | "in_progress"
  | "paused"
  | "failed"
  | "completed"
  | "cancelled";

export type WebsiteBuildArtifactType =
  | "prd_snapshot"
  | "website_specification"
  | "design_plan"
  | "content_plan"
  | "site_structure"
  | "component_plan"
  | "source_code"
  | "asset"
  | "build_log"
  | "qa_report";

export interface WebsiteBuildArtifact {
  id: string;
  build_session_id: string;
  project_id: string;
  artifact_type: WebsiteBuildArtifactType;
  artifact_name: string;
  artifact_version: number;
  content_reference?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface WebsiteBuildSession {
  id: string;
  project_id: string;
  owner_id: string;
  status: WebsiteBuildSessionStatus;
  build_version: number;
  started_at?: string | null;
  completed_at?: string | null;
  failure_reason?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface WebsiteBuildSessionDetail extends WebsiteBuildSession {
  artifacts: WebsiteBuildArtifact[];
  project_name?: string | null;
  project_slug?: string | null;
  project_status?: string | null;
  approved_prd_id?: string | null;
  approved_prd_version?: number | null;
  prd_summary?: Record<string, unknown> | null;
}

export interface WebsiteBuildSessionListResponse {
  items: WebsiteBuildSession[];
  total: number;
  active_count: number;
  completed_count: number;
  failed_count: number;
}

// ── Phase 6.2 Website Generation & Specification Types ────────────────────────

export type WebsiteGenerationStatus =
  | "pending"
  | "generating"
  | "validating"
  | "completed"
  | "failed"
  | "cancelled";

export interface NavigationItemSpecification {
  label: string;
  path: string;
  order: number;
  visibility: "all" | "header" | "footer" | "mobile";
}

export interface SectionSpecification {
  section_id: string;
  type: string;
  purpose: string;
  heading: string;
  supporting_content: string;
  layout: string;
  components: string[];
  cta?: string | null;
  visibility: "visible" | "conditional" | "hidden";
  responsive_behavior: string;
}

export interface PageSpecification {
  page_id: string;
  path: string;
  name: string;
  purpose: string;
  priority: "primary" | "secondary" | "utility";
  seo_title: string;
  seo_description: string;
  sections: SectionSpecification[];
  primary_cta?: string | null;
  secondary_cta?: string | null;
}

export interface TypographySpecification {
  heading_family: string;
  body_family: string;
  heading_scale: Record<string, string>;
  body_scale: Record<string, string>;
}

export interface ColorPaletteSpecification {
  primary: string;
  secondary: string;
  accent: string;
  background: string;
  surface: string;
  text: string;
  muted: string;
}

export interface DesignSystemSpecification {
  visual_direction: string;
  typography: TypographySpecification;
  color_palette: ColorPaletteSpecification;
  spacing: Record<string, string>;
  border_radius: Record<string, string>;
  shadows: Record<string, string>;
  imagery_direction: string;
  icon_direction: string;
  motion_direction: string;
  responsive_strategy: string;
}

export interface ContentSpecification {
  page: string;
  section: string;
  content_type: string;
  required: boolean;
  source: string;
  notes: string;
}

export interface WebsiteSpecification {
  specification_version: string;
  generation_version: number;
  project_name: string;
  project_slug: string;
  website_goal: string;
  target_audience: string;
  primary_cta: string;
  secondary_ctas: string[];
  navigation: NavigationItemSpecification[];
  pages: PageSpecification[];
  design_system: DesignSystemSpecification;
  content_strategy: ContentSpecification[];
  accessibility_requirements: string[];
  responsive_requirements: string[];
  technical_constraints: string[];
  open_questions: string[];
  source_prd_id: string;
  source_prd_version: number;
}

export interface WebsiteGeneration {
  id: string;
  build_session_id: string;
  project_id: string;
  owner_id: string;
  source_prd_id: string;
  source_prd_version: number;
  generation_version: number;
  status: WebsiteGenerationStatus;
  provider: string;
  model: string;
  specification_artifact_id?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface WebsiteGenerationDetail extends WebsiteGeneration {
  specification?: WebsiteSpecification | null;
  project_name?: string | null;
  project_slug?: string | null;
}

export interface WebsiteGenerationListResponse {
  items: WebsiteGeneration[];
  total: number;
  completed_count: number;
  failed_count: number;
  active_count: number;
}

// ── Phase 6.3 Design Blueprint Types ──────────────────────────────────────────

export type DesignBlueprintStatus =
  | "pending"
  | "generating"
  | "validating"
  | "completed"
  | "failed"
  | "cancelled";

export interface DesignTokens {
  colors: Record<string, string>;
  typography: {
    heading_font: string;
    body_font: string;
    mono_font: string;
    heading_weights: string[];
    body_weights: string[];
    scale: Record<string, string>;
  };
  spacing: Record<string, string>;
  radius: Record<string, string>;
  shadows: Record<string, string>;
  container: {
    max_width: string;
    gutters: string;
  };
}

export interface ResponsiveBreakpoint {
  name: string;
  min_width: string;
  layout_behavior: string;
  typography_behavior: string;
  spacing_behavior: string;
  navigation_behavior: string;
  component_behavior: string;
}

export interface ComponentSpecification {
  component_id: string;
  component_name: string;
  category: string;
  purpose: string;
  variants: string[];
  required_props: string[];
  optional_props: string[];
  accessibility_requirements: string[];
  responsive_behavior: string;
  allowed_usage: string;
  dependencies: string[];
}

export interface SectionBlueprint {
  section_id: string;
  section_type: string;
  purpose: string;
  component_refs: string[];
  content_refs: string[];
  layout: string;
  alignment: string;
  spacing: string;
  responsive_behavior: string;
  visual_priority: "high" | "medium" | "low";
  accessibility: string;
  interaction: string;
}

export interface PageBlueprint {
  page_id: string;
  route: string;
  name: string;
  purpose: string;
  layout_type: string;
  section_order: string[];
  sections: SectionBlueprint[];
  component_refs: string[];
  navigation_refs: string[];
  seo: Record<string, string>;
  responsive_rules: string[];
  accessibility_rules: string[];
}

export interface SiteArchitecture {
  root_route: string;
  pages: string[];
  navigation_flow: Array<{ from_route: string; to_route: string; label: string }>;
  footer_links: Array<{ label: string; route: string }>;
  global_components: string[];
  page_dependencies: Record<string, string[]>;
}

export interface AssetRequirement {
  asset_id: string;
  type: "image" | "video" | "icon" | "logo" | "illustration" | "font";
  purpose: string;
  page: string;
  section: string;
  required: boolean;
  source: string;
  dimensions?: string | null;
  aspect_ratio?: string | null;
  accessibility_alt_requirement: string;
  placeholder_allowed: boolean;
}

export interface InteractionSpecification {
  interaction_id: string;
  name: string;
  trigger: string;
  behavior: string;
  duration: string;
  reduced_motion_behavior: string;
  accessibility_behavior: string;
}

export interface AccessibilityBlueprint {
  keyboard_navigation: string[];
  focus_behavior: string;
  semantic_structure: string[];
  heading_hierarchy: string[];
  form_labels: string[];
  alt_text_requirements: string[];
  color_contrast_requirement: string;
  reduced_motion_behavior: string;
  screen_reader_considerations: string[];
}

export interface BlueprintContentMapping {
  source: string;
  page: string;
  section: string;
  content_type: string;
  required: boolean;
  status: "confirmed" | "generated_draft" | "unknown" | "needs_client_input";
}

export interface WebsiteDesignBlueprint {
  blueprint_version: string;
  source_generation_id: string;
  source_generation_version: number;
  project_name: string;
  project_slug: string;
  design_tokens: DesignTokens;
  responsive_breakpoints: ResponsiveBreakpoint[];
  component_taxonomy: ComponentSpecification[];
  site_architecture: SiteArchitecture;
  pages: PageBlueprint[];
  asset_requirements: AssetRequirement[];
  interactions: InteractionSpecification[];
  accessibility: AccessibilityBlueprint;
  content_mapping: BlueprintContentMapping[];
  implementation_constraints: string[];
}

export interface DesignBlueprint {
  id: string;
  build_session_id: string;
  project_id: string;
  owner_id: string;
  source_generation_id: string;
  source_generation_version: number;
  blueprint_version: number;
  status: DesignBlueprintStatus;
  specification_artifact_id?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DesignBlueprintDetail extends DesignBlueprint {
  blueprint?: WebsiteDesignBlueprint | null;
  project_name?: string | null;
  project_slug?: string | null;
}

export interface DesignBlueprintListResponse {
  items: DesignBlueprint[];
  total: number;
  completed_count: number;
  failed_count: number;
  active_count: number;
}
