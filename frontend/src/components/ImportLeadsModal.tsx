import { useRef, useState } from "react";
import { api } from "../api";
import type { LeadImportPreview, LeadImportSummary } from "../types";

const EXPECTED = [
  "company",
  "country",
  "website",
  "industry",
  "materials",
  "manufacturing_process",
  "business_type",
  "buying_signal",
  "contact_role",
  "contact_name",
  "contact_email",
];

const STATUS_LABEL: Record<string, string> = {
  valid: "Valid",
  duplicate: "Duplicate",
  failed: "Failed",
};

export default function ImportLeadsModal({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (result: LeadImportSummary) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<LeadImportPreview | null>(null);
  const [result, setResult] = useState<LeadImportSummary | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setFile(null);
    setPreview(null);
    setResult(null);
    setError(null);
  };

  const onPreview = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setPreview(await api.previewLeads(file));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const onImport = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.importLeads(file);
      setResult(res);
      onDone(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>Import Leads (CSV / Excel)</h2>
          <button className="secondary" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
          Accepted columns (case/space insensitive; aliases like "name",
          "material", "process", "role", "email" are accepted):
          <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 6 }}>
            {EXPECTED.map((c) => (
              <span key={c} className="chip">
                {c}
              </span>
            ))}
          </div>
          <div style={{ marginTop: 6 }}>
            <code>company</code> is required and maps to the lead name.
            Duplicate companies / websites are skipped. The file is previewed
            before anything is written.
          </div>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx,.xlsm,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            reset();
          }}
          style={{ marginBottom: 12 }}
        />

        {error && <div className="error">{error}</div>}

        {!result && preview && (
          <div className="import-preview">
            <div className="import-stats">
              <div className="stat">
                <span className="stat-num">{preview.total_rows}</span>
                <span className="stat-label">Total rows</span>
              </div>
              <div className="stat ok">
                <span className="stat-num">{preview.valid_count}</span>
                <span className="stat-label">Will import</span>
              </div>
              <div className="stat warn">
                <span className="stat-num">{preview.duplicate_count}</span>
                <span className="stat-label">Duplicates</span>
              </div>
              <div className="stat bad">
                <span className="stat-num">{preview.failed_count}</span>
                <span className="stat-label">Failed</span>
              </div>
            </div>

            {preview.rows.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                  Rows needing attention ({preview.rows.length} shown):
                </div>
                <table className="preview-table">
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Company</th>
                      <th>Status</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((p) => (
                      <tr key={p.row}>
                        <td>{p.row}</td>
                        <td>{p.company ?? "—"}</td>
                        <td>
                          <span className={`badge badge-${p.status}`}>
                            {STATUS_LABEL[p.status] ?? p.status}
                          </span>
                        </td>
                        <td className="muted">{p.reason ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {result && (
          <div className="import-result">
            <div className="import-stats">
              <div className="stat">
                <span className="stat-num">{result.total_rows}</span>
                <span className="stat-label">Total rows</span>
              </div>
              <div className="stat ok">
                <span className="stat-num">{result.imported_count}</span>
                <span className="stat-label">Imported</span>
              </div>
              <div className="stat warn">
                <span className="stat-num">{result.skipped_count}</span>
                <span className="stat-label">Skipped</span>
              </div>
              <div className="stat bad">
                <span className="stat-num">{result.failed_count}</span>
                <span className="stat-label">Failed</span>
              </div>
            </div>

            {result.error_details.length > 0 && (
              <div className="import-errors">
                <div className="muted" style={{ fontSize: 12, margin: "10px 0 4px" }}>
                  Details ({Math.min(result.error_details.length, 50)}
                  {result.error_details.length > 50 ? "+" : ""} shown):
                </div>
                <ul>
                  {result.error_details.slice(0, 50).map((e, i) => (
                    <li key={i}>
                      <b>row {e.row}</b>
                      {e.company ? ` — ${e.company}` : ""}: {e.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div className="modal-actions">
          <button className="secondary" onClick={onClose}>
            Close
          </button>
          {!result && !preview && (
            <button disabled={!file || loading} onClick={onPreview}>
              {loading ? "Parsing…" : "Preview file"}
            </button>
          )}
          {!result && preview && (
            <button disabled={loading} onClick={onImport}>
              {loading
                ? "Importing…"
                : `Confirm import (${preview.valid_count})`}
            </button>
          )}
          {result && (
            <button className="secondary" onClick={onClose}>
              Done
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
