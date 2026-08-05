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

/** Parse the JSON lead_score_breakdown safely (accepts string or object). */
export function parseBreakdown(lead: CompanyLead): LeadScoreBreakdown | null {
  const raw = lead.lead_score_breakdown;
  if (!raw) return null;
  // Defensive: some responses may already deserialise the field to an object.
  if (typeof raw === "object" && raw !== null) {
    return raw as LeadScoreBreakdown;
  }
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null) {
      return parsed as LeadScoreBreakdown;
    }
  } catch {
    /* fall through */
  }
  return null;
}

/**
 * Safely render ANY lead-intelligence value as readable text.
 *
 * Objects / arrays are flattened to "key: value" pairs (nested values are
 * themselves formatted) — never blindly JSON.stringified. This is the
 * regression guard for the "Objects are not valid as a React child" crash:
 * the score breakdown contains a `weights` sub-object whose keys are
 * company_fit / procurement_signal / website_intent / contact_quality /
 * pdf_signal.
 */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value.map((v) => formatValue(v)).join(" · ");
  }
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${formatValue(v)}`)
      .join(" · ");
  }
  return String(value);
}

/** Human-readable breakdown labels. */
export const BREAKDOWN_LABELS: Record<string, string> = {
  company_fit_score: "Company Fit",
  procurement_signal_score: "Procurement Signal",
  website_intent_score: "Website Intent",
  contact_quality_score: "Contact Quality",
  pdf_signal_score: "PDF Signal",
  weights: "Component Weights",
};

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString();
}
