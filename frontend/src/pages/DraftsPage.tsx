import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { OutreachMessage } from "../types";
import { formatDate, scoreColor } from "../utils";

const STATUS_COLORS: Record<string, string> = {
  draft: "#6b7280",
  approved: "#d97706",
  sent: "#2563eb",
  replied: "#16a34a",
};

const GATE_COLORS: Record<string, string> = {
  ready: "#16a34a",
  review: "#d97706",
  blocked: "#dc2626",
};

const GATE_LABELS: Record<string, string> = {
  ready: "Ready",
  review: "Needs review",
  blocked: "Blocked",
};

type GateFilter = "all" | "ready" | "review" | "blocked";

const GATE_FILTERS: { key: GateFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "ready", label: "Ready" },
  { key: "review", label: "Needs review" },
  { key: "blocked", label: "Blocked" },
];

export default function DraftsPage() {
  const navigate = useNavigate();
  const [drafts, setDrafts] = useState<OutreachMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<OutreachMessage | null>(null);
  const [gateFilter, setGateFilter] = useState<GateFilter>("all");
  const [releasing, setReleasing] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listDrafts({
        limit: 100,
        gate: gateFilter === "all" ? undefined : gateFilter,
      });
      setDrafts(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [gateFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const release = useCallback(
    async (id: number) => {
      setReleasing(id);
      try {
        await api.reviewDraftGate(id, "ready");
        await load();
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setReleasing(null);
      }
    },
    [load],
  );

  return (
    <div>
      <h1>Outreach Drafts</h1>
      <div className="sub">
        Review generated outreach emails awaiting approval. Drafts below the quality
        gate are flagged for review before they can be released.
      </div>

      <div className="toolbar">
        <div className="chip-group">
          {GATE_FILTERS.map((f) => (
            <button
              key={f.key}
              className={gateFilter === f.key ? "chip button active" : "chip button"}
              onClick={() => setGateFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <button className="secondary" onClick={load}>
          Refresh
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {loading && <div className="spinner">Loading drafts…</div>}

      {!loading && drafts.length === 0 && (
        <div className="muted">No drafts. Generate an email from a lead’s detail page.</div>
      )}

      {!loading && drafts.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Lead</th>
              <th>Subject</th>
              <th>Role</th>
              <th>Status</th>
              <th>Quality</th>
              <th>Gate</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {drafts.map((d) => (
              <tr key={d.id}>
                <td>{d.id}</td>
                <td>
                  <a
                    style={{ cursor: "pointer" }}
                    onClick={() => navigate(`/leads/${d.lead_id}`)}
                  >
                    #{d.lead_id}
                  </a>
                </td>
                <td>{d.subject}</td>
                <td>{d.contact_role ?? "—"}</td>
                <td>
                  <span
                    className="badge"
                    style={{ background: STATUS_COLORS[d.status] ?? "#6b7280" }}
                  >
                    {d.status}
                  </span>
                </td>
                <td>
                  {d.quality_score != null ? (
                    <span
                      className="badge"
                      style={{ background: scoreColor(d.quality_score) }}
                      title="Email quality score (0-100): 0.4×personalization + 0.4×relevance + 0.2×(100−spam)"
                    >
                      {d.quality_score}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  {d.quality_gate_status ? (
                    <span
                      className="badge"
                      style={{
                        background: GATE_COLORS[d.quality_gate_status] ?? "#6b7280",
                      }}
                      title="Quality gate: ready = releaseable, review/blocked = needs review"
                    >
                      {GATE_LABELS[d.quality_gate_status] ?? d.quality_gate_status}
                    </span>
                  ) : (
                    <span className="badge" style={{ background: "#9ca3af" }}>
                      Unscored
                    </span>
                  )}
                </td>
                <td>{formatDate(d.created_at)}</td>
                <td>
                  {d.quality_gate_status && d.quality_gate_status !== "ready" ? (
                    <button
                      className="secondary"
                      disabled={releasing === d.id}
                      onClick={() => release(d.id)}
                    >
                      {releasing === d.id ? "Releasing…" : "Release"}
                    </button>
                  ) : (
                    <button className="secondary" onClick={() => setSelected(d)}>
                      Review
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{selected.subject}</h2>
            <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
              Draft #{selected.id} · lead #{selected.lead_id} · role:{" "}
              {selected.contact_role ?? "—"} · quality:{" "}
              {selected.quality_score != null ? `${selected.quality_score}/100` : "—"} ·{" "}
              gate: {selected.quality_gate_status ?? "unscored"} ·{" "}
              {formatDate(selected.created_at)}
            </div>
            <pre style={{ maxHeight: 420, overflowY: "auto" }}>{selected.body}</pre>
            <div className="toolbar" style={{ justifyContent: "flex-end", marginTop: 14 }}>
              <button className="secondary" onClick={() => setSelected(null)}>
                Close
              </button>
              <button onClick={() => navigate(`/leads/${selected.lead_id}`)}>
                Open Lead
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
