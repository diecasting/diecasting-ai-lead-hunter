import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api";
import type {
  CompanyLead,
  LeadEmailVerification,
  LeadTimeline,
  OutreachMessage,
  ReplyAnalysis,
} from "../types";
import {
  priorityColor,
  priorityBadge,
  scoreColor,
  parseBreakdown,
  BREAKDOWN_LABELS,
  formatDate,
} from "../utils";
import { ValueView } from "../components/ValueView";
import LeadFormModal from "../components/LeadFormModal";

// Phase 4.6 lead pipeline status set.
const STATUS_FLOW = ["new", "contacted", "sent", "replied", "qualified", "rfq", "customer", "closed"];

const EVENT_LABELS: Record<string, string> = {
  generated: "Email generated",
  approved: "Draft approved",
  sent: "Email sent",
  replied: "Lead replied",
  opened: "Opened",
  bounced: "Bounced",
};

// Phase 6 Stage 2: reply intent display mapping.
const INTENT_LABELS: Record<string, string> = {
  interested: "Interested",
  rfq_request: "RFQ Request",
  technical_question: "Technical Question",
  price_request: "Price Request",
  supplier_existing: "Existing Supplier",
  not_interested: "Not Interested",
  out_of_office: "Out of Office",
  unknown: "Unknown",
};

const INTENT_COLORS: Record<string, string> = {
  interested: "#16a34a",
  rfq_request: "#9333ea",
  technical_question: "#2563eb",
  price_request: "#d97706",
  supplier_existing: "#64748b",
  not_interested: "#dc2626",
  out_of_office: "#94a3b8",
  unknown: "#6b7280",
};

// Phase 6.5: e-mail verification status colours (valid / invalid / unknown).
const EMAIL_STATUS_COLORS: Record<string, string> = {
  valid: "#16a34a",
  invalid: "#dc2626",
  unknown: "#d97706",
};

const emailStatusColor = (s?: string | null) =>
  EMAIL_STATUS_COLORS[s ?? "unknown"] ?? "#6b7280";

export default function LeadDetailPage() {
  const { id } = useParams();
  const leadId = Number(id);
  const navigate = useNavigate();

  const [lead, setLead] = useState<CompanyLead | null>(null);
  const [messages, setMessages] = useState<OutreachMessage[]>([]);
  const [timeline, setTimeline] = useState<LeadTimeline | null>(null);
  const [replyAnalyses, setReplyAnalyses] = useState<ReplyAnalysis[]>([]);
  const [replyText, setReplyText] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [edit, setEdit] = useState(false);
  const [verification, setVerification] = useState<LeadEmailVerification | null>(null);
  const [verifying, setVerifying] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [l, msgs, tl, analyses] = await Promise.all([
        api.getLead(leadId),
        api.listLeadMessages(leadId).catch(() => []),
        api.getLeadTimeline(leadId).catch(() => null),
        api.listReplyAnalyses(leadId).catch(() => []),
      ]);
      setLead(l);
      setMessages(msgs);
      setTimeline(tl);
      setReplyAnalyses(analyses);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    load();
  }, [load]);

  const wrap = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const analyzeReply = async () => {
    const text = replyText.trim();
    if (!text) return;
    setBusy("reply");
    setError(null);
    try {
      await api.analyzeReply(leadId, text);
      setReplyText("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const verifyEmail = async () => {
    if (!lead?.contact_email) return;
    setVerifying(true);
    setError(null);
    try {
      const res = await api.verifyLeadEmail(leadId);
      setVerification(res);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setVerifying(false);
    }
  };

  if (loading) return <div className="spinner">Loading lead #{leadId}…</div>;
  if (!lead) return <div className="error">{error ?? "Lead not found."}</div>;

  const breakdown = parseBreakdown(lead);

  return (
    <div>
      <button className="secondary" onClick={() => navigate("/leads")}>
        ← Back to Leads
      </button>
      <h1>{lead.name}</h1>
      <div className="sub">
        Lead #{lead.id} · created {formatDate(lead.created_at)}
      </div>
      {error && <div className="error">{error}</div>}

      <div className="grid grid-2">
        <div className="card">
          <h2>Profile</h2>
          <dl className="kv">
            <dt>Website</dt>
            <dd>
              {lead.website ? (
                <a href={lead.website} target="_blank" rel="noreferrer">
                  {lead.website}
                </a>
              ) : (
                "—"
              )}
            </dd>
            <dt>Industry</dt>
            <dd>{lead.industry ?? "—"}</dd>
            <dt>Country</dt>
            <dd>{lead.country ?? "—"}</dd>
            <dt>Business Type</dt>
            <dd>{lead.business_type ?? "—"}</dd>
            <dt>Materials</dt>
            <dd>{lead.materials ?? "—"}</dd>
            <dt>Process</dt>
            <dd>{lead.manufacturing_process ?? "—"}</dd>
            <dt>Buying Signal</dt>
            <dd>{lead.buying_signal ?? "—"}</dd>
            <dt>Contact Email</dt>
            <dd>{lead.contact_email ?? "—"}</dd>
            <dt>Do Not Contact</dt>
            <dd>{lead.do_not_contact ? "YES" : "no"}</dd>
            <dt>Description</dt>
            <dd>{lead.description ?? "—"}</dd>
          </dl>
          <div style={{ marginTop: 14 }}>
            <button className="secondary" onClick={() => setEdit(true)}>
              Edit
            </button>
          </div>
        </div>

        <div className="card">
          <h2>Scores & Quality</h2>
          <dl className="kv">
            <dt>Priority</dt>
            <dd>
              <span className="badge" style={{ background: priorityColor(lead.priority) }}>
                {priorityBadge(lead.priority)}
              </span>
            </dd>
            <dt>Lead Score</dt>
            <dd>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <strong style={{ fontSize: 18 }}>{lead.lead_score ?? "—"}</strong>
                <div className="bar" style={{ width: 140 }}>
                  <span
                    style={{
                      width: `${lead.lead_score ?? 0}%`,
                      background: scoreColor(lead.lead_score),
                    }}
                  />
                </div>
              </div>
            </dd>
            <dt>Sales Priority</dt>
            <dd>{lead.sales_priority ?? "—"}</dd>
            <dt>AI Score</dt>
            <dd>{lead.ai_score ?? "—"}</dd>
            <dt>Crawl Status</dt>
            <dd>{lead.crawl_status ?? "—"}</dd>
          </dl>

          {breakdown && (
            <>
              <h2>Score Breakdown</h2>
              {Object.entries(breakdown).map(([k, v]) => (
                <div key={k} style={{ marginBottom: 8 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 13,
                    }}
                  >
                    <span>{BREAKDOWN_LABELS[k] ?? k}</span>
                    <span>
                      <ValueView value={v ?? "—"} />
                    </span>
                  </div>
                  <div className="bar">
                    <span
                      style={{
                        width: `${typeof v === "number" ? v : 0}%`,
                        background: scoreColor(v as number),
                      }}
                    />
                  </div>
                </div>
              ))}
            </>
          )}

          {lead.ai_summary && (
            <>
              <h2>AI Summary</h2>
              <pre>{lead.ai_summary}</pre>
            </>
          )}
        </div>
      </div>

      <div className="card">
        <h2>Email Verification</h2>
        {!lead.contact_email ? (
          <div className="muted">No contact email on this lead to verify.</div>
        ) : (
          <>
            <dl className="kv">
              <dt>Contact Email</dt>
              <dd>{lead.contact_email}</dd>
              <dt>Status</dt>
              <dd>
                <span
                  className="badge"
                  style={{
                    background: emailStatusColor(
                      verification?.email_status ?? lead.email_status,
                    ),
                  }}
                >
                  {(verification?.email_status ?? lead.email_status ?? "unknown").toUpperCase()}
                </span>
                {lead.email_status === "invalid" && (
                  <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>
                    sending blocked (no MX / undeliverable)
                  </span>
                )}
              </dd>
              <dt>Confidence</dt>
              <dd>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <strong style={{ fontSize: 18 }}>
                    {verification?.email_confidence_score ??
                      lead.email_confidence_score ??
                      "—"}
                  </strong>
                  <div className="bar" style={{ width: 140 }}>
                    <span
                      style={{
                        width: `${
                          verification?.email_confidence_score ??
                          lead.email_confidence_score ??
                          0
                        }%`,
                        background: scoreColor(
                          verification?.email_confidence_score ??
                            lead.email_confidence_score ??
                            0,
                        ),
                      }}
                    />
                  </div>
                </div>
              </dd>
            </dl>

            {verification && (
              <>
                <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                  {verification.reason}
                </div>
                <h2 style={{ marginTop: 14 }}>Checks</h2>
                {verification.checks.map((c, i) => (
                  <div key={i} style={{ marginBottom: 6 }}>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        fontSize: 13,
                      }}
                    >
                      <span style={{ textTransform: "capitalize" }}>
                        {c.verifier}
                      </span>
                      <span
                        className="badge"
                        style={{
                          background: emailStatusColor(c.status),
                          fontSize: 11,
                        }}
                      >
                        {c.status.toUpperCase()}
                      </span>
                    </div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {c.reason}
                    </div>
                  </div>
                ))}
              </>
            )}

            <div style={{ marginTop: 14 }}>
              <button
                className="secondary"
                disabled={verifying}
                onClick={verifyEmail}
              >
                {verifying ? "Verifying…" : "Verify email"}
              </button>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <h2>Pipeline Actions</h2>
        <div className="toolbar">
          <button
            disabled={!!busy}
            onClick={() => wrap("analyze", () => api.analyzeLead(leadId))}
          >
            {busy === "analyze" ? "Running…" : "Run AI Analysis"}
          </button>
          <button
            disabled={!!busy}
            onClick={() => wrap("intel", () => api.runIntelligence(leadId))}
          >
            {busy === "intel" ? "Running…" : "Run Full Intelligence"}
          </button>
          <button
            disabled={!!busy}
            onClick={() => wrap("email", () => api.generateEmail(leadId))}
          >
            {busy === "email" ? "Generating…" : "Generate Outreach Email"}
          </button>
        </div>

        <div className="toolbar">
          <label className="muted" style={{ fontSize: 13 }}>
            Set pipeline status:
          </label>
          <select
            defaultValue=""
            onChange={(e) => {
              const v = e.target.value;
              if (v) wrap(`status:${v}`, () => api.updateLeadStatus(leadId, v));
            }}
          >
            <option value="">— choose —</option>
            {STATUS_FLOW.map((s) => (
              <option key={s} value={s} disabled={s === lead.lead_status}>
                {s}
                {s === lead.lead_status ? " (current)" : ""}
              </option>
            ))}
          </select>
          <span className="muted" style={{ fontSize: 13 }}>
            current stage: <strong>{lead.lead_status}</strong>
          </span>
        </div>
      </div>

      <div className="card">
        <h2>Reply Intelligence</h2>
        <div className="toolbar" style={{ alignItems: "flex-start" }}>
          <textarea
            rows={3}
            value={replyText}
            onChange={(e) => setReplyText(e.target.value)}
            placeholder="Paste a customer reply to auto-classify intent and update the CRM…"
            style={{ flex: 1, minWidth: 280 }}
          />
          <button disabled={!!busy || !replyText.trim()} onClick={analyzeReply}>
            {busy === "reply" ? "Analyzing…" : "Analyze Reply"}
          </button>
        </div>

        {replyAnalyses.length === 0 ? (
          <div className="muted" style={{ marginTop: 10 }}>
            No replies analyzed yet — paste a customer reply above.
          </div>
        ) : (
          <>
            {(() => {
              const latest = replyAnalyses[0];
              return (
                <div
                  className="card"
                  style={{
                    background: "var(--panel-2)",
                    marginTop: 12,
                    marginBottom: 12,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span
                      className="badge"
                      style={{
                        background: INTENT_COLORS[latest.intent] ?? "#6b7280",
                      }}
                    >
                      {INTENT_LABELS[latest.intent] ?? latest.intent}
                    </span>
                    <strong>{latest.confidence_score ?? 0}% confidence</strong>
                    <span className="muted" style={{ fontSize: 12 }}>
                      {formatDate(latest.created_at)}
                    </span>
                  </div>
                  <div className="muted" style={{ fontSize: 13, marginTop: 8 }}>
                    Recommended: {latest.recommended_action ?? "—"}
                  </div>
                  {latest.applied_actions && latest.applied_actions.length > 0 && (
                    <div style={{ marginTop: 6 }}>
                      {latest.applied_actions.map((a) => (
                        <span key={a} className="chip">
                          ✓ {a}
                        </span>
                      ))}
                    </div>
                  )}
                  <pre style={{ marginTop: 8, fontSize: 12 }}>{latest.reply_text}</pre>
                </div>
              );
            })()}
            {replyAnalyses.length > 1 && (
              <div className="muted" style={{ fontSize: 12 }}>
                Earlier analyses:{" "}
                {replyAnalyses.slice(1).map((a) => (
                  <span key={a.id} className="chip">
                    {INTENT_LABELS[a.intent] ?? a.intent} (
                    {a.confidence_score ?? 0}%)
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <div className="card">
        <h2>Outreach Timeline</h2>
        {!timeline || timeline.events.length === 0 ? (
          <div className="muted">
            No outreach activity yet — generate an email to start the timeline.
          </div>
        ) : (
          <div className="timeline">
            {timeline.events.map((e) => (
              <div key={e.id} className="timeline-item">
                <div className="timeline-dot" />
                <div>
                  <div>
                    <strong>{EVENT_LABELS[e.event_type] ?? e.event_type}</strong>
                    <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>
                      {formatDate(e.created_at)}
                    </span>
                  </div>
                  {e.message_subject ? (
                    <div className="muted" style={{ fontSize: 12 }}>
                      {e.message_subject}
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h2>Outreach Messages ({messages.length})</h2>
        {messages.length === 0 && (
          <div className="muted">No emails generated yet. Use “Generate Outreach Email” above.</div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className="card"
            style={{ background: "var(--panel-2)", marginBottom: 10 }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <strong>{m.subject}</strong>
              <span>
                <span className="badge" style={{ background: "var(--accent)" }}>
                  {m.status}
                </span>{" "}
                <span
                  className="badge"
                  style={{
                    background:
                      m.send_status === "sent"
                        ? "#16a34a"
                        : m.send_status === "failed"
                          ? "#dc2626"
                          : "#6b7280",
                  }}
                >
                  {m.send_status ?? "draft"}
                </span>
              </span>
            </div>
            <div className="muted" style={{ fontSize: 12, margin: "4px 0 8px" }}>
              role: {m.contact_role ?? "—"} · quality:{" "}
              {m.quality_score != null ? (
                <span style={{ color: scoreColor(m.quality_score) }}>
                  {m.quality_score}/100
                </span>
              ) : (
                "—"
              )}{" "}
              · {formatDate(m.created_at)} · opens: {m.open_count} · clicks:{" "}
              {m.click_count}
              {m.sent_at ? (
                <>
                  {" "}
                  · sent: <strong>{formatDate(m.sent_at)}</strong>
                </>
              ) : (
                ""
              )}
            </div>
            <pre>{m.body}</pre>
          </div>
        ))}
      </div>

      {edit && (
        <LeadFormModal
          lead={lead}
          onClose={() => setEdit(false)}
          onCreated={(updated) => {
            setEdit(false);
            setLead(updated);
          }}
        />
      )}
    </div>
  );
}
