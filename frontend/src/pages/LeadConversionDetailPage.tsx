import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { AcceptResult, ConversionSignal } from "../types";
import { formatDate, formatValue } from "../utils";

function labelColor(label?: string | null): string {
  switch (label) {
    case "hot":
      return "#dc2626";
    case "warm":
      return "#d97706";
    case "cold":
      return "#2563eb";
    default:
      return "#9ca3af";
  }
}

function priorityColor(priority?: string | null): string {
  switch (priority) {
    case "high":
      return "#dc2626";
    case "medium":
      return "#d97706";
    case "low":
      return "#6b7280";
    default:
      return "#9ca3af";
  }
}

function temperatureColor(score?: number | null): string {
  if (score == null) return "#9ca3af";
  if (score >= 70) return "#dc2626";
  if (score >= 40) return "#d97706";
  return "#2563eb";
}

/** Friendly labels for the recommendation actions. */
const ACTION_LABELS: Record<string, string> = {
  prepare_quote: "Prepare Quotation",
  send_capability_case: "Send Capability / Value Case",
  stop_sequence: "Stop Outreach Sequence",
  suppress_contact: "Suppress Contact (Spam)",
  follow_up_sequence: "Continue Follow-up Sequence",
  monitor: "Monitor",
  engineering_response: "Engineering Response",
};

function actionLabel(action?: string | null): string {
  if (!action) return "—";
  return ACTION_LABELS[action] ?? action;
}

export default function LeadConversionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const leadId = Number(id);
  const navigate = useNavigate();

  const [signal, setSignal] = useState<ConversionSignal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);
  const [acceptResult, setAcceptResult] = useState<AcceptResult | null>(null);
  const [acceptError, setAcceptError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getConversionSignal(leadId);
      setSignal(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    load();
  }, [load]);

  const onAccept = async (force: boolean) => {
    if (!signal?.next_action) return;
    setAccepting(true);
    setAcceptError(null);
    setAcceptResult(null);
    try {
      const res = await api.acceptRecommendation(leadId, signal.next_action, force);
      setAcceptResult(res);
      // Refresh the signal so any post-accept state (do_not_contact etc.) is current.
      await load();
    } catch (e) {
      setAcceptError((e as Error).message);
    } finally {
      setAccepting(false);
    }
  };

  return (
    <div>
      <button className="secondary" onClick={() => navigate("/conversion")}>
        ← Back to Hot Leads
      </button>

      <h1>Conversion Intelligence — Lead #{leadId}</h1>

      {error && <div className="error">{error}</div>}
      {loading && <div className="spinner">Loading conversion intelligence…</div>}

      {!loading && signal && (
        <div className="card-grid">
          {/* Primary metrics */}
          <section className="card">
            <h3>Conversion Snapshot</h3>
            <table className="kv">
              <tbody>
                <tr>
                  <td>Intent Score</td>
                  <td>
                    <span className="mono">{signal.intent_score ?? "—"}</span>
                    {signal.dominant_intent && (
                      <span className="muted"> · {signal.dominant_intent}</span>
                    )}
                  </td>
                </tr>
                <tr>
                  <td>Temperature</td>
                  <td>
                    <span
                      className="badge"
                      style={{ background: labelColor(signal.temperature_label) }}
                    >
                      {signal.temperature_label ?? "—"}
                    </span>
                    <div
                      className="bar"
                      style={{ width: 120, display: "inline-block", marginLeft: 8 }}
                    >
                      <span
                        style={{
                          width: `${signal.temperature_score ?? 0}%`,
                          background: temperatureColor(signal.temperature_score),
                        }}
                      />
                    </div>
                    <span className="muted">{signal.temperature_score ?? "—"}</span>
                  </td>
                </tr>
                <tr>
                  <td>Next Action</td>
                  <td>
                    <span className="badge badge-action">
                      {actionLabel(signal.next_action)}
                    </span>
                  </td>
                </tr>
                <tr>
                  <td>Recommendation Confidence</td>
                  <td>
                    <span
                      className="badge"
                      style={{
                        background: priorityColor(signal.next_action_priority),
                      }}
                    >
                      {(signal.next_action_priority ?? "—").toUpperCase()}
                    </span>
                  </td>
                </tr>
                <tr>
                  <td>Reason</td>
                  <td className="muted">{signal.next_action_reason ?? "—"}</td>
                </tr>
                <tr>
                  <td>Computed At</td>
                  <td className="muted">{formatDate(signal.computed_at)}</td>
                </tr>
              </tbody>
            </table>
          </section>

          {/* Signal sources */}
          <section className="card">
            <h3>Signal Sources</h3>
            {signal.signal_sources && Object.keys(signal.signal_sources).length > 0 ? (
              <table className="kv">
                <tbody>
                  {Object.entries(signal.signal_sources).map(([k, v]) => (
                    <tr key={k}>
                      <td>{k}</td>
                      <td>{formatValue(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="muted">No signal sources recorded.</div>
            )}
          </section>
        </div>
      )}

      {/* Acceptance actions */}
      {!loading && signal && signal.next_action && (
        <section className="card accept-panel">
          <h3>Recommendation Actions</h3>
          <p className="muted">
            Accepting creates a follow-up SalesTask for this recommendation. This is
            a human-in-the-loop action — no task is created automatically.
          </p>
          <div className="row-actions">
            <button
              disabled={accepting}
              onClick={() => onAccept(false)}
            >
              {accepting ? "Accepting…" : `Accept: ${actionLabel(signal.next_action)}`}
            </button>
            {signal.next_action_priority !== "high" && (
              <button
                className="secondary"
                disabled={accepting}
                onClick={() => onAccept(true)}
                title="Force-accept even if the action differs from the current recommendation"
              >
                Force Accept
              </button>
            )}
          </div>

          {acceptError && <div className="error">{acceptError}</div>}
          {acceptResult && (
            <div className="success">
              {acceptResult.already_exists
                ? "An open task already exists for this recommendation."
                : "SalesTask created."}{" "}
              <strong>
                #{acceptResult.task_id} — {acceptResult.title}
              </strong>{" "}
              <span className="muted">
                ({acceptResult.priority} / {acceptResult.status})
              </span>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
