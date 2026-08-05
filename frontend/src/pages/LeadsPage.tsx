import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { CompanyLead } from "../types";
import { priorityColor, priorityBadge, scoreColor } from "../utils";
import LeadFormModal from "../components/LeadFormModal";
import ImportLeadsModal from "../components/ImportLeadsModal";

export default function LeadsPage() {
  const navigate = useNavigate();
  const [leads, setLeads] = useState<CompanyLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [priority, setPriority] = useState("");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listLeads({
        priority: priority || undefined,
        limit: 200,
      });
      setLeads(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [priority]);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = leads.filter((l) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      l.name.toLowerCase().includes(q) ||
      (l.industry ?? "").toLowerCase().includes(q) ||
      (l.country ?? "").toLowerCase().includes(q) ||
      (l.website ?? "").toLowerCase().includes(q)
    );
  });

  const onDelete = async (id: number) => {
    if (!confirm(`Delete lead #${id}? This cannot be undone.`)) return;
    try {
      await api.deleteLead(id);
      setLeads((prev) => prev.filter((l) => l.id !== id));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div>
      <h1>Leads</h1>
      <div className="sub">
        {leads.length} leads loaded. Click a lead to view details, run analysis, or generate outreach.
      </div>

      <div className="toolbar">
        <input
          placeholder="Search name / industry / country / website"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ minWidth: 280 }}
        />
        <select value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="">All priorities</option>
          <option value="HIGH">HIGH</option>
          <option value="MEDIUM">MEDIUM</option>
          <option value="LOW">LOW</option>
        </select>
        <button onClick={() => setShowForm(true)}>+ New Lead</button>
        <button onClick={() => setShowImport(true)}>⤓ Import Leads</button>
        <button className="secondary" onClick={load}>
          Refresh
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {loading && <div className="spinner">Loading leads…</div>}

      {!loading && (
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Company</th>
              <th>Industry</th>
              <th>Country</th>
              <th>Source</th>
              <th>Priority</th>
              <th>Lead Score</th>
              <th>Sales Priority</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((l) => (
              <tr key={l.id}>
                <td>{l.id}</td>
                <td>
                  <a
                    onClick={() => navigate(`/leads/${l.id}`)}
                    style={{ cursor: "pointer" }}
                  >
                    {l.name}
                  </a>
                </td>
                <td>{l.industry ?? "—"}</td>
                <td>{l.country ?? "—"}</td>
                <td>
                  <span className={`badge badge-source badge-${l.lead_source ?? "import"}`}>
                    {l.lead_source ?? "import"}
                  </span>
                </td>
                <td>
                  <span
                    className="badge"
                    style={{ background: priorityColor(l.priority) }}
                  >
                    {priorityBadge(l.priority)}
                  </span>
                </td>
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span>{l.lead_score ?? "—"}</span>
                    <div className="bar" style={{ width: 60 }}>
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
                <td>{l.lead_status}</td>
                <td>
                  <div className="row-actions">
                    <button
                      className="secondary"
                      onClick={() => navigate(`/leads/${l.id}`)}
                    >
                      View
                    </button>
                    <button className="danger" onClick={() => onDelete(l.id)}>
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={10} className="muted">
                  No leads match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {showForm && (
        <LeadFormModal
          onClose={() => setShowForm(false)}
          onCreated={(l) => {
            setShowForm(false);
            navigate(`/leads/${l.id}`);
          }}
        />
      )}

      {showImport && (
        <ImportLeadsModal
          onClose={() => setShowImport(false)}
          onDone={() => {
            setShowImport(false);
            load();
          }}
        />
      )}
    </div>
  );
}
