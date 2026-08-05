// Shared TypeScript types mirroring the FastAPI schemas in app/schemas/*.

export interface CompanyLead {
  id: number;
  name: string;
  website?: string | null;
  domain?: string | null;
  country?: string | null;
  region?: string | null;
  industry?: string | null;
  description?: string | null;
  employee_count?: number | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  contact_name?: string | null;
  source?: string | null;
  lead_source?: string;
  lead_status: string;
  sales_priority?: string | null;
  business_type?: string | null;
  materials?: string | null;
  manufacturing_process?: string | null;
  buying_signal?: string | null;
  contact_role?: string | null;
  do_not_contact: boolean;
  bounce_count: number;
  acquisition_channel?: string | null;
  lead_score?: number | null;
  lead_score_breakdown?: string | null;
  priority?: string | null;
  ai_score?: number | null;
  ai_relevant?: boolean | null;
  ai_summary?: string | null;
  ai_signals?: string | null;
  crawl_status?: string;
  contact_emails?: unknown[] | null;
  pages_crawled?: number;
  created_at: string;
  updated_at: string;
}

export interface LeadScoreBreakdown {
  company_fit_score?: number;
  procurement_signal_score?: number;
  website_intent_score?: number;
  contact_quality_score?: number;
  pdf_signal_score?: number;
  [key: string]: number | undefined;
}

export interface OutreachMessage {
  id: number;
  lead_id: number;
  subject: string;
  body: string;
  contact_role?: string | null;
  status: string;
  sent_time?: string | null;
  sender?: string | null;
  recipient?: string | null;
  is_followup: boolean;
  followup_seq: number;
  open_count: number;
  click_count: number;
  quality_score?: number | null;
  quality_gate_status?: string | null;
  created_at: string;
}

export interface RankingResponse {
  count: number;
  filters: { min_score: number; priority: string | null };
  by_priority: Record<string, CompanyLead[]>;
  ranked: CompanyLead[];
}

export type Priority = "HIGH" | "MEDIUM" | "LOW" | null | undefined;

export interface ImportRowError {
  row: number;
  company?: string | null;
  reason: string;
}

export interface LeadImportSummary {
  total_rows: number;
  imported_count: number;
  skipped_count: number;
  failed_count: number;
  error_details: ImportRowError[];
}

export interface ImportPreviewRow {
  row: number;
  company?: string | null;
  website?: string | null;
  status: "valid" | "duplicate" | "failed";
  reason?: string | null;
}

export interface LeadImportPreview {
  total_rows: number;
  valid_count: number;
  duplicate_count: number;
  failed_count: number;
  rows: ImportPreviewRow[];
}
