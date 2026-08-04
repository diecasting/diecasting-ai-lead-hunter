// Small presentation helpers shared across pages.
import type { CompanyLead, LeadScoreBreakdown } from "./types";

/** Color tokens per priority label. Accepts nullable API strings. */
export function priorityColor(priority: string | null | undefined): string {
  switch (priority) {
    case "HIGH":
      return "#dc2626"; // red = hot (Chinese market convention: up=red)
    case "MEDIUM":
      return "#d97706"; // amber
    case "LOW":
      return "#6b7280"; // gray
    default:
      return "#9ca3af";
  }
}

export function priorityBadge(priority: string | null | undefined): string {
  if (!priority) return "—";
  return priority;
}

/** A colored score bar for 0–100 values. */
export function scoreColor(score: number | null | undefined): string {
  if (score == null) return "#9ca3af";
  if (score >= 80) return "#dc2626";
  if (score >= 50) return "#d97706";
  return "#6b7280";
}

/** Parse the JSON lead_score_breakdown string safely. */
export function parseBreakdown(lead: CompanyLead): LeadScoreBreakdown | null {
  if (!lead.lead_score_breakdown) return null;
  try {
    const parsed = JSON.parse(lead.lead_score_breakdown);
    if (typeof parsed === "object" && parsed !== null) {
      return parsed as LeadScoreBreakdown;
    }
  } catch {
    /* fall through */
  }
  return null;
}

/** Human-readable breakdown labels. */
export const BREAKDOWN_LABELS: Record<string, string> = {
  company_fit_score: "Company Fit",
  procurement_signal_score: "Procurement Signal",
  website_intent_score: "Website Intent",
  contact_quality_score: "Contact Quality",
  pdf_signal_score: "PDF Signal",
};

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString();
}
