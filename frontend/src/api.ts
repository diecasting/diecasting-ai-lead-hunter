// Thin fetch-based API client. All paths are relative to `/api` which is
// proxied to the FastAPI backend by Vite (see vite.config.ts). Set
// VITE_API_BASE to override (e.g. a deployed backend URL) at build time.
import type {
  CompanyLead,
  CreateJobResponse,
  DiscoveryJob,
  DiscoveryResult,
  DiscoverySchedule,
  FollowUpSequence,
  LeadImportPreview,
  LeadImportSummary,
  LeadTimeline,
  OutreachFollowUp,
  OutreachMessage,
  RankingResponse,
  SendDraftResponse,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  query?: Record<string, string | number | boolean | undefined>,
): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== "") {
        url.searchParams.set(k, String(v));
      }
    }
  }
  const res = await fetch(url.toString(), {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const err = await res.json();
      detail = err.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${method} ${path} failed (${res.status}): ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  // ---- Leads ------------------------------------------------------------
  listLeads: (params?: {
    skip?: number;
    limit?: number;
    priority?: string;
    relevant_only?: boolean;
  }) =>
    request<CompanyLead[]>("GET", "/leads", undefined, {
      skip: params?.skip,
      limit: params?.limit ?? 200,
      priority: params?.priority,
      relevant_only: params?.relevant_only,
    }),

  getLead: (id: number) => request<CompanyLead>("GET", `/leads/${id}`),

  createLead: (payload: Partial<CompanyLead>) =>
    request<CompanyLead>("POST", "/leads", payload),

  updateLead: (id: number, payload: Partial<CompanyLead>) =>
    request<CompanyLead>("PATCH", `/leads/${id}`, payload),

  deleteLead: (id: number) => request<void>("DELETE", `/leads/${id}`),

  // Dry-run an import file: returns per-row outcomes without writing anything.
  previewLeads: async (file: File): Promise<LeadImportPreview> => {
    const url = new URL(`${BASE}/leads/import/preview`, window.location.origin);
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(url.toString(), { method: "POST", body: form });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const err = await res.json();
        detail = err.detail ?? detail;
      } catch {
        /* ignore */
      }
      throw new Error(`Preview failed (${res.status}): ${detail}`);
    }
    return (await res.json()) as LeadImportPreview;
  },

  importLeads: async (file: File): Promise<LeadImportSummary> => {
    const url = new URL(`${BASE}/leads/import`, window.location.origin);
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(url.toString(), { method: "POST", body: form });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const err = await res.json();
        detail = err.detail ?? detail;
      } catch {
        /* ignore */
      }
      throw new Error(`Import failed (${res.status}): ${detail}`);
    }
    return (await res.json()) as LeadImportSummary;
  },

  analyzeLead: (id: number) =>
    request<CompanyLead>("POST", `/leads/${id}/analyze`),

  runIntelligence: (id: number, crawl = true, extractPdfs = true) =>
    request<CompanyLead>("POST", `/leads/${id}/intelligence`, undefined, {
      crawl,
      extract_pdfs: extractPdfs,
    }),

  updateLeadStatus: (id: number, lead_status: string) =>
    request<CompanyLead>("PATCH", `/leads/${id}/status`, { lead_status }),

  getLeadTimeline: (id: number) =>
    request<LeadTimeline>("GET", `/leads/${id}/timeline`),

  // ---- Outreach ---------------------------------------------------------
  generateEmail: (leadId: number) =>
    request<OutreachMessage>("POST", `/leads/${leadId}/generate-email`),

  listDrafts: (params?: { skip?: number; limit?: number; gate?: string }) =>
    request<OutreachMessage[]>("GET", "/outreach/drafts", undefined, {
      skip: params?.skip,
      limit: params?.limit ?? 100,
      gate: params?.gate,
    }),

  listLeadMessages: (leadId: number, status?: string) =>
    request<OutreachMessage[]>("GET", `/outreach/leads/${leadId}/messages`, undefined, {
      status,
    }),

  // Reviewer override of a draft's quality gate (release a review/blocked draft).
  reviewDraftGate: (messageId: number, gateStatus: string) =>
    request<OutreachMessage>("PATCH", `/outreach/drafts/${messageId}/gate`, {
      gate_status: gateStatus,
    }),

  // Send an approved (gate=ready) draft through the sending pipeline.
  sendDraft: (messageId: number) =>
    request<SendDraftResponse>("POST", `/outreach/drafts/${messageId}/send`),

  // ---- CRM / Quality ----------------------------------------------------
  ranking: (params?: { limit?: number; min_score?: number; priority?: string }) =>
    request<RankingResponse>("GET", "/crm/ranking", undefined, {
      limit: params?.limit ?? 50,
      min_score: params?.min_score ?? 0,
      priority: params?.priority,
    }),

  highValue: (limit = 50) =>
    request<CompanyLead[]>("GET", "/crm/high-value", undefined, { limit }),

  pipeline: (statuses?: string) =>
    request<Record<string, CompanyLead[]>>("GET", "/crm/pipeline", undefined, {
      statuses,
    }),

  // ---- Discovery (Phase 5 Stage 1) -------------------------------------
  analyzeUrl: (url: string) =>
    request<DiscoveryResult>("POST", "/discovery/analyze-url", { url }),

  listDiscoveries: (limit = 50) =>
    request<DiscoveryResult[]>("GET", "/discovery", undefined, { limit }),

  addDiscoveryToCrm: (discoveryId: number) =>
    request<CompanyLead>("POST", `/discovery/${discoveryId}/lead`),

  // ---- Discovery jobs (Phase 5 Stage 2) ---------------------------------
  createDiscoveryJob: (keyword: string) =>
    request<CreateJobResponse>("POST", "/discovery/jobs", { keyword }),

  getDiscoveryJob: (jobId: number) =>
    request<DiscoveryJob>("GET", `/discovery/jobs/${jobId}`),

  runDiscoveryJob: (jobId: number) =>
    request<DiscoveryJob>("POST", `/discovery/jobs/${jobId}/run`),

  // ---- Discovery schedules (Phase 5 Stage 3) ----------------------------
  createSchedule: (payload: {
    keyword: string;
    frequency?: string;
    enabled?: boolean;
    lead_score_threshold?: number;
    confidence_threshold?: number;
  }) => request<DiscoverySchedule>("POST", "/discovery/schedules", payload),

  listSchedules: () => request<DiscoverySchedule[]>("GET", "/discovery/schedules"),

  updateSchedule: (id: number, payload: Partial<DiscoverySchedule>) =>
    request<DiscoverySchedule>("PATCH", `/discovery/schedules/${id}`, payload),

  deleteSchedule: (id: number) => request<void>("DELETE", `/discovery/schedules/${id}`),

  scheduleHistory: (id: number) =>
    request<DiscoveryJob[]>("GET", `/discovery/schedules/${id}/history`),

  runScheduleNow: (id: number) =>
    request<DiscoveryJob>("POST", `/discovery/schedules/${id}/run`),

  // ---- Follow-up automation (Phase 6 Stage 1) ---------------------------
  createSequence: (payload: {
    name: string;
    steps: { delay_days: number; template: string }[];
    enabled?: boolean;
  }) => request<FollowUpSequence>("POST", "/outreach/sequences", payload),

  listSequences: () => request<FollowUpSequence[]>("GET", "/outreach/sequences"),

  updateSequence: (id: number, payload: Partial<FollowUpSequence>) =>
    request<FollowUpSequence>("PATCH", `/outreach/sequences/${id}`, payload),

  startFollowup: (leadId: number, sequenceId?: number) =>
    request<OutreachFollowUp[]>(
      "POST",
      `/outreach/leads/${leadId}/start-followup`,
      sequenceId ? { sequence_id: sequenceId } : {},
    ),

  listFollowups: (params?: { status?: string; lead_id?: number }) =>
    request<OutreachFollowUp[]>("GET", "/outreach/followups", undefined, {
      status: params?.status,
      lead_id: params?.lead_id,
    }),

  updateFollowupStatus: (id: number, status: "pending" | "cancelled") =>
    request<OutreachFollowUp>("PATCH", `/outreach/followups/${id}`, { status }),

  processFollowups: () =>
    request<{
      processed: number;
      generated: number;
      sent: number;
      cancelled: number;
      skipped_no_recipient: number;
      send_failed: number;
    }>("POST", "/outreach/followups/process"),
};
