import { useRef, useState } from "react";
import { api } from "../api";
import type { LeadImportResult } from "../types";

const EXPECTED = [
  "company",
  "country",
  "website",
  "industry",
  "materials",
  "manufacturing_process",
  "buying_signal",
  "contact_role",
];

export default function ImportLeadsModal({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (result: LeadImportResult) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<LeadImportResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const onUpload = async () => {
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
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>Import Leads (CSV / Excel)</h2>
          <button className="secondary" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
          Expected columns (case/space insensitive; aliases like "name",
          "material", "process", "role" are accepted):
          <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 6 }}>
            {EXPECTED.map((c) => (
              <span key={c} className="chip">
                {c}
              </span>
            ))}
          </div>
          <div style={{ marginTop: 6 }}>
            <code>company</code> is required and maps to the lead name.
            Duplicate companies / websites are skipped.
          </div>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx,.xlsm,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setResult(null);
            setError(null);
          }}
          style={{ marginBottom: 12 }}
        />

        {error && <div className="error">{error}</div>}

        {result && (
          <div className="import-result">
            <div className="import-stats">
              <div className="stat">
                <span className="stat-num">{result.total}</span>
                <span className="stat-label">Total</span>
              </div>
              <div className="stat ok">
                <span className="stat-num">{result.imported}</span>
                <span className="stat-label">Imported</span>
              </div>
              <div className="stat warn">
                <span className="stat-num">{result.skipped}</span>
                <span className="stat-label">Skipped</span>
              </div>
              <div className="stat bad">
                <span className="stat-num">{result.failed}</span>
                <span className="stat-label">Failed</span>
              </div>
            </div>

            {result.errors.length > 0 && (
              <div className="import-errors">
                <div className="muted" style={{ fontSize: 12, margin: "10px 0 4px" }}>
                  Details ({Math.min(result.errors.length, 50)}
                  {result.errors.length > 50 ? "+" : ""} shown):
                </div>
                <ul>
                  {result.errors.slice(0, 50).map((e, i) => (
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
          <button disabled={!file || loading} onClick={onUpload}>
            {loading ? "Importing…" : "Import"}
          </button>
        </div>
      </div>
    </div>
  );
}
