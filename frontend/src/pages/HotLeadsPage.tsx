import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { CompanyLead, HotLead } from "../types";
import { formatDate } from "../utils";

type LabelFilter = "" | "hot" | "warm" | "cold";

/** Map a temperature label to a readable badge color. */
function labelColor(label?: string | null): string {
  switch (label) {
    case "hot":
      return "#dc2626"; // red = hot
    case "warm":
      return "#d97706"; // amber
    case "cold":
      return "#2563eb"; // blue
    default:
      return "#9ca3af";
  }
}

/** Map next-action priority (high/medium/low) to a confidence-style badge. */
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

export default function HotLeadsPage() {
  const navigate = useNavigate();
  const [leads, setLeads] = useState<HotLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState<LabelFilter>("");
  const [minTemp, setMinTemp] = useState("");
  const [includeSuppressed, setIncludeSuppressed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const hot = await api.getHotLeads({
        label: label || undefined,
        min_temperature: minTemp ? Number(minTemp) : undefined,
        include_suppressed: includeSuppressed,
        limit: 200,
      });

      // Enrich with country / industry from the Leads API (the hot-leads
      // endpoint only returns lead_id + company_name per the backend schema).
      let metaById: Record<number, CompanyLead> = {};
      try {
        const all = await api.listLeads({ limit: 500, relevant_only: false });
        metaById = Object.fromEntries(all.map((l) => [l.id, l]));
      } catch {
        // Optional enrichment — ignore if the leads call fails.
      }

      const enriched: HotLead[] = hot.map((h) => {
        const meta = metaById[h.lead_id];
        return {
          ...h,
          country: meta?.country ?? null,
          industry: meta?.industry ?? null,
        };
      });
      setLeads(enriched);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [label, minTemp, includeSuppressed]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <h1>Conversion Intelligence — Hot Leads</h1>
      <div className="sub">
        Leads ranked by conversion temperature and recommendation priority.
        Click a lead to view its conversion intelligence detail.
      </div>

      <div className="toolbar">
        <select value={label} onChange={(e) => setLabel(e.target.value as LabelFilter)}>
          <option value="">All temperatures</option>
          <option value="hot">Hot</option>
          <option value="warm">Warm</option>
          <option value="cold">Cold</option>
        </select>
        <input
          placeholder="Min temperature (0-100)"
          value={minTemp}
          onChange={(e) => setMinTemp(e.target.value)}
          style={{ width: 160 }}
        />
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <input
            type="checkbox"
            checked={includeSuppressed}
            onChange={(e) => setIncludeSuppressed(e.target.checked)}
          />
          Include suppressed
        </label>
        <button className="secondary" onClick={load}>
          Refresh
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {loading && <div className="spinner">Loading hot leads…</div>}

      {!loading && (
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Company</th>
              <th>Industry</th>
              <th>Country</th>
              <th>Intent</th>
              <th>Temperature</th>
              <th>Next Action</th>
              <th>Confidence</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {leads.map((h) => (
              <tr key={h.lead_id}>
                <td>{h.lead_id}</td>
                <td>
                  <a
                    onClick={() => navigate(`/conversion/${h.lead_id}`)}
                    style={{ cursor: "pointer" }}
                  >
                    {h.company_name ?? `Lead #${h.lead_id}`}
                  </a>
                </td>
                <td>{h.industry ?? "—"}</td>
                <td>{h.country ?? "—"}</td>
                <td>
                  <span className="mono">
                    {h.intent_score ?? "—"}
                    {h.dominant_intent ? ` · ${h.dominant_intent}` : ""}
                  </span>
                </td>
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span
                      className="badge"
                      style={{ background: labelColor(h.temperature_label) }}
                    >
                      {h.temperature_label ?? "—"}
                    </span>
                    <div className="bar" style={{ width: 60 }}>
                      <span
                        style={{
                          width: `${h.temperature_score ?? 0}%`,
                          background: temperatureColor(h.temperature_score),
                        }}
                      />
                    </div>
                    <span className="muted">{h.temperature_score ?? "—"}</span>
                  </div>
                </td>
                <td>
                  <span className="badge badge-action">
                    {h.next_action ?? "—"}
                  </span>
                </td>
                <td>
                  <span
                    className="badge"
                    style={{ background: priorityColor(h.next_action_priority) }}
                  >
                    {(h.next_action_priority ?? "—").toUpperCase()}
                  </span>
                </td>
                <td>
                  <span className="muted">{formatDate(h.computed_at)}</span>
                </td>
              </tr>
            ))}
            {leads.length === 0 && (
              <tr>
                <td colSpan={9} className="muted">
                  No hot leads. Run conversion analysis (reply intelligence or
                  recompute) to populate conversion signals.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
