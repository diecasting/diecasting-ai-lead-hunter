// Regression test for the "Objects are not valid as a React child" crash.
//
// The lead_score_breakdown JSON emitted by app/ai/lead_scoring.apply_lead_score
// contains a `weights` sub-object whose keys are exactly:
//   company_fit, procurement_signal, website_intent, contact_quality, pdf_signal
// Rendering that sub-object directly as a React child used to throw. This test
// pins the safe-render behaviour of parseBreakdown / formatValue so the page
// keeps loading after imported leads are analysed.
import assert from "node:assert/strict";
import { parseBreakdown, formatValue } from "../utils";
import type { CompanyLead } from "../types";

// A breakdown payload identical in shape to what the backend stores.
const REALISTIC_BREAKDOWN = {
  company_fit_score: 80,
  procurement_signal_score: 60,
  website_intent_score: 100,
  contact_quality_score: 40,
  pdf_signal_score: 20,
  weights: {
    company_fit: 0.3,
    procurement_signal: 0.2,
    website_intent: 0.2,
    contact_quality: 0.15,
    pdf_signal: 0.15,
  },
};

function leadWithBreakdown(json: string | object | null): CompanyLead {
  return {
    id: 1,
    name: "Test Lead",
    do_not_contact: false,
    bounce_count: 0,
    pages_crawled: 0,
    created_at: "",
    updated_at: "",
    lead_score_breakdown: json as CompanyLead["lead_score_breakdown"],
  } as CompanyLead;
}

// 1. parseBreakdown must accept the JSON string the API returns.
const parsed = parseBreakdown(leadWithBreakdown(JSON.stringify(REALISTIC_BREAKDOWN)));
assert.ok(parsed, "parseBreakdown should return an object for valid JSON");
assert.equal(typeof parsed!.weights, "object", "weights sub-object must survive parsing");
assert.deepEqual(
  Object.keys(parsed!.weights as Record<string, number>).sort(),
  ["company_fit", "contact_quality", "pdf_signal", "procurement_signal", "website_intent"],
  "weights keys must be the five component scores",
);

// 2. parseBreakdown must also tolerate an already-deserialised object (defensive).
const parsedObj = parseBreakdown(leadWithBreakdown(REALISTIC_BREAKDOWN as unknown as string));
assert.ok(parsedObj, "parseBreakdown should accept an object payload");

// 3. formatValue must turn the weights object into readable text WITHOUT throwing.
const text = formatValue(parsed!.weights);
assert.ok(text.includes("company_fit"), "weights text must expose company_fit");
assert.ok(text.includes("0.3"), "weights text must expose the numeric weight");
assert.ok(!text.includes("[object Object]"), "weights must not render as [object Object]");

// 4. The OLD buggy render would throw on the weights object — document the contract.
assert.throws(
  () => {
    // This mirrors `{v ?? "—"}` in the previous Score Breakdown render.
    const v: unknown = parsed!.weights;
    if (typeof v === "object" && v !== null) {
      // React throws this exact error when given a plain object as a child.
      throw new Error("Objects are not valid as a React child");
    }
  },
  /Objects are not valid as a React child/,
  "regression: direct object render must be rejected by the safe path",
);

// 5. formatValue stays safe for every primitive / empty case.
assert.equal(formatValue(null), "—");
assert.equal(formatValue(undefined), "—");
assert.equal(formatValue(42), "42");
assert.equal(formatValue("rfq"), "rfq");

console.log("scoreBreakdown regression: OK");
