import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api";
import type { CompanyLead, LeadTimeline, OutreachMessage } from "../types";
import {
  priorityColor,
  priorityBadge,
  scoreColor,
  parseBreakdown,
  BREAKDOWN_LABELS,
  formatDate,
} from "../utils";
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

export default function LeadDetailPage() {
  const { id } = useParams();
  const leadId = Number(id);
  const navigate = useNavigate();

  const [lead, setLead] = useState<CompanyLead | null>(null);
  const [messages, setMessages] = useState<OutreachMessage[]>([]);
  const [timeline, setTimeline] = useState<LeadTimeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [edit, setEdit] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [l, msgs, tl] = await Promise.all([
        api.getLead(leadId),
        api.listLeadMessages(leadId).catch(() => []),
        api.getLeadTimeline(leadId).catch(() => null),
      ]);
      setLead(l);
      setMessages(msgs);
      setTimeline(tl);
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
                    <span>{v ?? "—"}</span>
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
