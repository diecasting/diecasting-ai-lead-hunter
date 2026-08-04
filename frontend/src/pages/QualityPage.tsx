import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { CompanyLead } from "../types";
import { priorityColor, priorityBadge, scoreColor } from "../utils";

type Tab = "ranking" | "high-value";

export default function QualityPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("ranking");
  const [ranked, setRanked] = useState<CompanyLead[]>([]);
  const [highValue, setHighValue] = useState<CompanyLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [minScore, setMinScore] = useState(0);
  const [priority, setPriority] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [r, h] = await Promise.all([
        api.ranking({ min_score: minScore, priority: priority || undefined, limit: 100 }),
        api.highValue(100),
      ]);
      setRanked(r.ranked);
      setHighValue(h);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [minScore, priority]);

  useEffect(() => {
    load();
  }, [load]);

  const rows = tab === "ranking" ? ranked : highValue;

  return (
    <div>
      <h1>Quality & Ranking</h1>
      <div className="sub">
        Leads ranked by composite lead score (Phase 3 engine) with quality breakdown.
        HIGH priority (red) = score &gt; 80.
      </div>

      <div className="toolbar">
        <button
          className={tab === "ranking" ? "" : "secondary"}
          onClick={() => setTab("ranking")}
        >
          Ranking
        </button>
        <button
          className={tab === "high-value" ? "" : "secondary"}
          onClick={() => setTab("high-value")}
        >
          High Value (untouched)
        </button>

        {tab === "ranking" && (
          <>
            <select value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="">All priorities</option>
              <option value="HIGH">HIGH</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="LOW">LOW</option>
            </select>
            <label className="muted" style={{ fontSize: 13 }}>
              Min score:
            </label>
            <input
              type="number"
              min={0}
              max={100}
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
              style={{ width: 80 }}
            />
            <button className="secondary" onClick={load}>
              Apply
            </button>
          </>
        )}
        <button className="secondary" onClick={load}>
          Refresh
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {loading && <div className="spinner">Loading…</div>}

      {!loading && (
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Company</th>
              <th>Priority</th>
              <th>Lead Score</th>
              <th>Sales Priority</th>
              <th>Industry</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((l, i) => (
              <tr key={l.id}>
                <td>{i + 1}</td>
                <td>
                  <a style={{ cursor: "pointer" }} onClick={() => navigate(`/leads/${l.id}`)}>
                    {l.name}
                  </a>
                </td>
                <td>
                  <span className="badge" style={{ background: priorityColor(l.priority) }}>
                    {priorityBadge(l.priority)}
                  </span>
                </td>
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <strong>{l.lead_score ?? "—"}</strong>
                    <div className="bar" style={{ width: 70 }}>
                      <span
                        style={{
                          width: `${l.lead_score ?? 0}%`,
                          background: scoreColor(l.lead_score),
                        }}
                      />
                    </div>
                  </div>
                </td>
                <td>{l.sales_priority ?? "—"}</td>
                <td>{l.industry ?? "—"}</td>
                <td>{l.lead_status}</td>
                <td>
                  <button className="secondary" onClick={() => navigate(`/leads/${l.id}`)}>
                    View
                  </button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  No leads match the current filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
