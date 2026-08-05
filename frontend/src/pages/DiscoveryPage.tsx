import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { DiscoveryResult } from "../types";
import { scoreColor } from "../utils";

export default function DiscoveryPage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DiscoveryResult | null>(null);
  const [added, setAdded] = useState<number | null>(null);
  const [history, setHistory] = useState<DiscoveryResult[]>([]);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await api.listDiscoveries(20));
    } catch {
      /* non-fatal */
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const analyze = async () => {
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    setAdded(null);
    try {
      setResult(await api.analyzeUrl(url.trim()));
      await loadHistory();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const addToCrm = async () => {
    if (!result) return;
    setBusy(true);
    setError(null);
    try {
      const lead = await api.addDiscoveryToCrm(result.id);
      setAdded(lead.id);
      await loadHistory();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h1>Lead Discovery</h1>
      <div className="sub">
        Analyse a prospect's website to extract their manufacturing profile,
        score the lead and recommend a contact — then add it to the CRM.
        No email is sent automatically.
      </div>

      <div className="card">
        <div className="toolbar">
          <input
            placeholder="https://prospect-company.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && analyze()}
            style={{ minWidth: 320 }}
          />
          <button disabled={!url.trim() || busy} onClick={analyze}>
            {busy ? "Analysing…" : "Run AI Analysis"}
          </button>
        </div>
        {error && <div className="error">{error}</div>}
      </div>

      {result && (
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <h2 style={{ margin: 0 }}>{result.company_name}</h2>
            {added != null ? (
              <span className="badge" style={{ background: "#16a34a" }}>
                Added to CRM as lead #{added}
              </span>
            ) : result.lead_id != null ? (
              <span className="badge" style={{ background: "#2563eb" }}>
                Already in CRM (lead #{result.lead_id})
              </span>
            ) : null}
          </div>
          <div className="muted" style={{ fontSize: 13, margin: "6px 0 12px" }}>
            {result.website} · {result.industry ?? "—"} ·{" "}
            {result.country ?? "—"} · {result.business_type ?? "—"}
          </div>

          <div className="import-stats" style={{ marginBottom: 14 }}>
            <div className="stat">
              <span className="stat-num">
                {result.lead_score != null ? result.lead_score : "—"}
              </span>
              <span className="stat-label">Lead score</span>
            </div>
            <div className="stat">
              <span className="stat-num">
                {result.confidence_score != null ? result.confidence_score : "—"}
              </span>
              <span className="stat-label">Confidence</span>
            </div>
            <div className="stat ok">
              <span className="stat-num">{result.recommended_contact_role ?? "—"}</span>
              <span className="stat-label">Recommended role</span>
            </div>
            <div className="stat">
              <span className="stat-num">
                {result.procurement_type || "—"}
                {result.procurement_score != null ? ` (${result.procurement_score})` : ""}
              </span>
              <span className="stat-label">Procurement</span>
            </div>
          </div>

          {result.lead_score != null && (
            <div className="bar" style={{ width: "100%", marginBottom: 14 }}>
              <span
                style={{
                  width: `${result.lead_score}%`,
                  background: scoreColor(result.lead_score),
                }}
              />
            </div>
          )}

          <dl className="kv">
            <dt>Description</dt>
            <dd>{result.description || "—"}</dd>
            <dt>Products</dt>
            <dd>
              {result.products.length ? result.products.join(", ") : "—"}
            </dd>
            <dt>Industries served</dt>
            <dd>
              {result.industries_served.length
                ? result.industries_served.join(", ")
                : "—"}
            </dd>
            <dt>Materials</dt>
            <dd>
              {result.detected_materials.length
                ? result.detected_materials.join(", ")
                : "—"}
            </dd>
            <dt>Processes</dt>
            <dd>
              {result.detected_processes.length
                ? result.detected_processes.join(", ")
                : "—"}
            </dd>
            <dt>Buying signals</dt>
            <dd>
              {result.buying_signals.length ? (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {result.buying_signals.map((s) => (
                    <span key={s} className="chip">
                      {s}
                    </span>
                  ))}
                </div>
              ) : (
                "—"
              )}
            </dd>
            <dt>Supplier opportunities</dt>
            <dd>
              {result.supplier_opportunities.length ? (
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {result.supplier_opportunities.map((o) => (
                    <li key={o}>{o}</li>
                  ))}
                </ul>
              ) : (
                "—"
              )}
            </dd>
          </dl>

          <div className="toolbar" style={{ justifyContent: "flex-end", marginTop: 12 }}>
            {added == null && result.lead_id == null && (
              <button disabled={busy} onClick={addToCrm}>
                {busy ? "Adding…" : "+ Add to CRM"}
              </button>
            )}
            {added != null && (
              <button onClick={() => navigate(`/leads/${added}`)}>Open lead</button>
            )}
          </div>
        </div>
      )}

      {history.length > 0 && (
        <div className="card">
          <h2>Recent Discoveries ({history.length})</h2>
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Company</th>
                <th>Industry</th>
                <th>Lead Score</th>
                <th>Confidence</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {history.map((d) => (
                <tr key={d.id}>
                  <td>{d.id}</td>
                  <td>{d.company_name}</td>
                  <td>{d.industry ?? "—"}</td>
                  <td>{d.lead_score ?? "—"}</td>
                  <td>{d.confidence_score ?? "—"}</td>
                  <td>
                    {d.lead_id != null ? (
                      <span className="badge" style={{ background: "#16a34a" }}>
                        In CRM #{d.lead_id}
                      </span>
                    ) : (
                      <span className="badge" style={{ background: "#6b7280" }}>
                        Pending
                      </span>
                    )}
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
