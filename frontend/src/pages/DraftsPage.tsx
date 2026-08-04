import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { OutreachMessage } from "../types";
import { formatDate } from "../utils";

const STATUS_COLORS: Record<string, string> = {
  draft: "#6b7280",
  approved: "#d97706",
  sent: "#2563eb",
  replied: "#16a34a",
};

export default function DraftsPage() {
  const navigate = useNavigate();
  const [drafts, setDrafts] = useState<OutreachMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<OutreachMessage | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listDrafts({ limit: 100 });
      setDrafts(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <h1>Outreach Drafts</h1>
      <div className="sub">
        Review generated outreach emails awaiting approval. Click a draft to read the full body.
      </div>

      <div className="toolbar">
        <button className="secondary" onClick={load}>
          Refresh
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      {loading && <div className="spinner">Loading drafts…</div>}

      {!loading && drafts.length === 0 && (
        <div className="muted">No drafts. Generate an email from a lead’s detail page.</div>
      )}

      {!loading && (
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Lead</th>
              <th>Subject</th>
              <th>Role</th>
              <th>Status</th>
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
                <td>{formatDate(d.created_at)}</td>
                <td>
                  <button className="secondary" onClick={() => setSelected(d)}>
                    Review
                  </button>
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
              {selected.contact_role ?? "—"} · {formatDate(selected.created_at)}
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
