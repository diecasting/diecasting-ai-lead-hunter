import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { FollowUpSequence, OutreachFollowUp } from "../types";
import { formatDate } from "../utils";

const TEMPLATES = ["technical_followup", "rfq_followup", "value_prop_followup"];

const STATUS_COLORS: Record<string, string> = {
  pending: "#6b7280",
  generated: "#2563eb",
  sent: "#16a34a",
  cancelled: "#dc2626",
};

type StepRow = { delay_days: number; template: string };

export default function FollowupAutomationPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [steps, setSteps] = useState<StepRow[]>([
    { delay_days: 3, template: "technical_followup" },
    { delay_days: 7, template: "rfq_followup" },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sequences, setSequences] = useState<FollowUpSequence[]>([]);
  const [followups, setFollowups] = useState<OutreachFollowUp[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [processResult, setProcessResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [seqs, fus] = await Promise.all([
        api.listSequences(),
        api.listFollowups(statusFilter ? { status: statusFilter } : undefined),
      ]);
      setSequences(seqs);
      setFollowups(fus);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const wrap = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const updateStep = (i: number, patch: Partial<StepRow>) =>
    setSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));

  const create = () =>
    wrap("create", () =>
      api.createSequence({ name: name.trim(), steps }).then(() => {
        setName("");
        setSteps([
          { delay_days: 3, template: "technical_followup" },
          { delay_days: 7, template: "rfq_followup" },
        ]);
      }),
    );

  const toggleSequence = (s: FollowUpSequence) =>
    wrap("toggle", () => api.updateSequence(s.id, { enabled: !s.enabled }));

  const toggleFollowup = (fu: OutreachFollowUp) =>
    wrap("pause", () =>
      api.updateFollowupStatus(fu.id, fu.status === "cancelled" ? "pending" : "cancelled"),
    );

  const processNow = () =>
    wrap("process", async () => {
      const r = await api.processFollowups();
      setProcessResult(
        `sent ${r.sent} · generated ${r.generated} · cancelled ${r.cancelled} · ` +
          `no-recipient ${r.skipped_no_recipient} · failed ${r.send_failed}`,
      );
    });

  return (
    <div>
      <h1>Follow-up Automation</h1>
      <div className="sub">
        Automatically generate and schedule follow-up emails for unanswered
        outreach. After an email is sent, follow-ups are scheduled from the
        lead's sequence and stop as soon as the lead replies, sends an RFQ,
        becomes a customer, or closes.
      </div>

      <div className="card">
        <h2>Create sequence</h2>
        <div className="toolbar" style={{ flexWrap: "wrap" }}>
          <input
            placeholder="Sequence name, e.g. Default 2-step"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ minWidth: 240 }}
          />
          <button disabled={!name.trim() || busy} onClick={create}>
            Create sequence
          </button>
        </div>

        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
          {steps.map((s, i) => (
            <div key={i} className="toolbar">
              <span className="muted" style={{ fontSize: 13 }}>
                Step {i + 1}:
              </span>
              <label className="muted" style={{ fontSize: 13 }}>
                delay
                <input
                  type="number"
                  min={1}
                  value={s.delay_days}
                  onChange={(e) =>
                    updateStep(i, { delay_days: Number(e.target.value) })
                  }
                  style={{ width: 60, marginLeft: 6 }}
                />
                days
              </label>
              <select
                value={s.template}
                onChange={(e) => updateStep(i, { template: e.target.value })}
              >
                {TEMPLATES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              <button
                className="danger"
                disabled={steps.length <= 1}
                onClick={() => setSteps((prev) => prev.filter((_, idx) => idx !== i))}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
        <button
          className="secondary"
          onClick={() =>
            setSteps((prev) => [...prev, { delay_days: 10, template: "value_prop_followup" }])
          }
        >
          + Add step
        </button>
        {error && <div className="error">{error}</div>}
      </div>

      {sequences.length > 0 && (
        <div className="card">
          <h2>Sequences ({sequences.length})</h2>
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Steps</th>
                <th>Enabled</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sequences.map((s) => (
                <tr key={s.id}>
                  <td>{s.id}</td>
                  <td>{s.name}</td>
                  <td className="muted">
                    {s.steps
                      .map((st) => `+${st.delay_days}d ${st.template}`)
                      .join(" → ")}
                  </td>
                  <td>
                    <span
                      className="badge"
                      style={{ background: s.enabled ? "#16a34a" : "#6b7280" }}
                    >
                      {s.enabled ? "enabled" : "disabled"}
                    </span>
                  </td>
                  <td>
                    <button className="secondary" disabled={busy} onClick={() => toggleSequence(s)}>
                      {s.enabled ? "Disable" : "Enable"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <h2>Scheduled follow-ups</h2>
          <div className="toolbar">
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              <option value="pending">Pending</option>
              <option value="generated">Generated</option>
              <option value="sent">Sent</option>
              <option value="cancelled">Cancelled</option>
            </select>
            <button className="secondary" disabled={busy} onClick={processNow}>
              Process due now
            </button>
          </div>
        </div>
        {processResult && (
          <div className="muted" style={{ fontSize: 13, margin: "6px 0" }}>
            Last run: {processResult}
          </div>
        )}
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Lead</th>
              <th>Step</th>
              <th>Scheduled</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {followups.map((fu) => (
              <tr key={fu.id}>
                <td>{fu.id}</td>
                <td>
                  <a
                    style={{ cursor: "pointer" }}
                    onClick={() => navigate(`/leads/${fu.lead_id}`)}
                  >
                    {fu.lead_name ?? `#${fu.lead_id}`}
                  </a>
                </td>
                <td>{fu.step_number}</td>
                <td>{fu.scheduled_at ? formatDate(fu.scheduled_at) : "—"}</td>
                <td>
                  <span className="badge" style={{ background: STATUS_COLORS[fu.status] ?? "#6b7280" }}>
                    {fu.status}
                  </span>
                </td>
                <td>
                  {fu.status === "pending" || fu.status === "cancelled" ? (
                    <button className="secondary" disabled={busy} onClick={() => toggleFollowup(fu)}>
                      {fu.status === "cancelled" ? "Resume" : "Pause"}
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
            {followups.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  No follow-ups scheduled. Send an outreach email to auto-schedule them.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
