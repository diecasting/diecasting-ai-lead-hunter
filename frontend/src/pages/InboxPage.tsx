import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type {
  InboxProcessSummary,
  InboxStatus,
  InboxTestResult,
  IncomingEmail,
} from "../types";
import { formatDate } from "../utils";

// Phase 6 Stage 2 reply-intent display mapping (shared look with the lead
// detail Reply Intelligence card).
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

type Filter = "all" | "processed" | "unprocessed";

export default function InboxPage() {
  const [emails, setEmails] = useState<IncomingEmail[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<InboxProcessSummary | null>(null);
  const [status, setStatus] = useState<InboxStatus | null>(null);
  const [testResult, setTestResult] = useState<InboxTestResult | null>(null);
  const [testBusy, setTestBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [rows, st] = await Promise.all([
        filter === "unprocessed"
          ? api.listUnprocessedInbox()
          : api.listInbox({ processed: filter === "processed" ? "true" : undefined }),
        api.getInboxStatus().catch(() => null),
      ]);
      setEmails(rows);
      setStatus(st);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  const process = async () => {
    setBusy(true);
    setError(null);
    try {
      const s = await api.processInbox();
      setSummary(s);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const testConnection = async () => {
    setTestBusy(true);
    setError(null);
    try {
      setTestResult(await api.testInboxConnection());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setTestBusy(false);
    }
  };

  return (
    <div>
      <h1>Reply Inbox</h1>
      <div className="sub">
        Pull customer replies from the mailbox and feed them into the Reply
        Intelligence Engine (match lead → classify intent → apply CRM actions).
      </div>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>IMAP Connection</h2>
          <button className="secondary" disabled={testBusy} onClick={testConnection}>
            {testBusy ? "Testing…" : "Test IMAP Connection"}
          </button>
        </div>
        {status && (
          <div className="toolbar" style={{ marginTop: 10, flexWrap: "wrap" }}>
            <span
              className="badge"
              style={{ background: status.configured ? "#16a34a" : "#6b7280" }}
            >
              {status.provider} {status.configured ? "· configured" : "· dry-run"}
            </span>
            <span className="chip">
              server: {status.server || "—"}
              {status.use_ssl ? " (SSL)" : ""}
            </span>
            <span className="chip">username: {status.username || "—"}</span>
            <span className="chip">folder: {status.folder}</span>
            <span className="chip">
              fetched emails: <strong>{status.fetched_count}</strong>
            </span>
            <span className="chip">
              last check:{" "}
              <strong>{status.last_check_at ? formatDate(status.last_check_at) : "—"}</strong>
            </span>
          </div>
        )}
        {testResult && (
          <div
            className="card"
            style={{
              background: "var(--panel-2)",
              marginTop: 10,
              padding: 12,
            }}
          >
            <div>
              {testResult.ok ? (
                <span className="badge" style={{ background: "#16a34a" }}>
                  connected
                </span>
              ) : (
                <span className="badge" style={{ background: "#dc2626" }}>
                  failed
                </span>
              )}{" "}
              <strong>
                {testResult.provider} · {testResult.count} messages
                {testResult.configured ? "" : " (dry-run)"}
              </strong>
              {testResult.error && (
                <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>
                  {testResult.error}
                </div>
              )}
              {testResult.latest && testResult.latest.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  {testResult.latest.map((m, i) => (
                    <div key={i} style={{ fontSize: 12, marginBottom: 4 }}>
                      <span className="muted">
                        {m.sender_email ?? m.sender_name ?? "—"}
                      </span>
                      {" — "}
                      {m.subject ?? "(no subject)"}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <div className="toolbar">
          <button disabled={busy} onClick={process}>
            {busy ? "Processing…" : "Fetch & Process Inbox"}
          </button>
          <div className="toolbar" style={{ marginLeft: 8 }}>
            {(["all", "unprocessed", "processed"] as Filter[]).map((f) => (
              <button
                key={f}
                className={filter === f ? "primary" : "secondary"}
                onClick={() => setFilter(f)}
              >
                {f === "all" ? "All" : f === "unprocessed" ? "Unprocessed" : "Processed"}
              </button>
            ))}
          </div>
        </div>

        {summary && (
          <div className="import-stats" style={{ marginTop: 12 }}>
            <div className="stat ok">
              <span className="stat-num">{summary.new_emails}</span>
              <span className="stat-label">new fetched</span>
            </div>
            <div className="stat ok">
              <span className="stat-num">{summary.matched}</span>
              <span className="stat-label">matched</span>
            </div>
            <div className="stat warn">
              <span className="stat-num">{summary.analyzed}</span>
              <span className="stat-label">analyzed</span>
            </div>
            <div className="stat warn">
              <span className="stat-num">{summary.unmatched}</span>
              <span className="stat-label">unmatched</span>
            </div>
            <div className="stat">
              <span className="stat-num">{summary.duplicates}</span>
              <span className="stat-label">duplicates</span>
            </div>
          </div>
        )}
      </div>

      {loading ? (
        <div className="spinner">Loading inbox…</div>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Customer</th>
                <th>Email</th>
                <th>Subject</th>
                <th>Intent</th>
                <th>Confidence</th>
                <th>Action Taken</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {emails.length === 0 && (
                <tr>
                  <td colSpan={7} className="muted">
                    No inbox emails. Click “Fetch & Process Inbox” to pull replies.
                  </td>
                </tr>
              )}
              {emails.map((e) => (
                <tr key={e.id}>
                  <td>
                    {e.matched_lead_name ? (
                      <a href={`#/leads/${e.matched_lead_id}`}>{e.matched_lead_name}</a>
                    ) : (
                      <span className="muted">unmatched</span>
                    )}
                    {e.sender_name ? (
                      <div className="muted" style={{ fontSize: 12 }}>
                        {e.sender_name}
                      </div>
                    ) : null}
                  </td>
                  <td>
                    <a href={`mailto:${e.sender_email}`}>{e.sender_email}</a>
                  </td>
                  <td>
                    {e.subject ?? "—"}
                    <div className="muted" style={{ fontSize: 12 }}>
                      {formatDate(e.received_at)}
                    </div>
                  </td>
                  <td>
                    {e.intent ? (
                      <span
                        className="badge"
                        style={{
                          background: INTENT_COLORS[e.intent] ?? "#6b7280",
                        }}
                      >
                        {INTENT_LABELS[e.intent] ?? e.intent}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    {e.intent ? `${e.confidence_score ?? 0}%` : "—"}
                  </td>
                  <td>
                    {e.recommended_action ? (
                      <span style={{ fontSize: 13 }}>{e.recommended_action}</span>
                    ) : e.processed ? (
                      <span className="muted">—</span>
                    ) : (
                      <span className="muted">awaiting match</span>
                    )}
                  </td>
                  <td>
                    <span
                      className="badge"
                      style={{
                        background: e.processed ? "#16a34a" : "#6b7280",
                      }}
                    >
                      {e.processed ? "processed" : "unprocessed"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
