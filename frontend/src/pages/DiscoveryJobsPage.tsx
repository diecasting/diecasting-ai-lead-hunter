import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { DiscoveryJob, DiscoveryJobTask } from "../types";

export default function DiscoveryJobsPage() {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<DiscoveryJob | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const refresh = useCallback(async (jobId: number) => {
    try {
      const j = await api.getDiscoveryJob(jobId);
      setJob(j);
      if (j.status !== "running") {
        stopPolling();
        setBusy(false);
      }
    } catch (e) {
      setError((e as Error).message);
      stopPolling();
      setBusy(false);
    }
  }, [stopPolling]);

  const start = async () => {
    if (!keyword.trim()) return;
    setBusy(true);
    setError(null);
    setSelected(new Set());
    try {
      const { job_id } = await api.createDiscoveryJob(keyword.trim());
      await api.runDiscoveryJob(job_id);
      await refresh(job_id);
      // Poll until the synchronous run completes (fast local runs may finish
      // in one shot; keep a short poll for long crawls).
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(() => refresh(job_id), 1500);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const toggle = (discoveryId: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(discoveryId)) next.delete(discoveryId);
      else next.add(discoveryId);
      return next;
    });
  };

  const addSelectedToCrm = async () => {
    if (selected.size === 0 || !job) return;
    setBusy(true);
    setError(null);
    try {
      for (const discoveryId of selected) {
        await api.addDiscoveryToCrm(discoveryId);
      }
      setSelected(new Set());
      await refresh(job.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const candidates = (job?.tasks ?? []).filter((t) => t.discovery_id != null);
  const pct =
    job && job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0;

  return (
    <div>
      <h1>Discovery Jobs</h1>
      <div className="sub">
        Discover multiple industrial prospects from a search keyword, analyse
        them automatically, then bulk-add the best ones to the CRM. No emails
        are sent automatically.
      </div>

      <div className="card">
        <div className="toolbar">
          <input
            placeholder='e.g. "automotive aluminum die casting supplier Germany"'
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && start()}
            style={{ minWidth: 380 }}
          />
          <button disabled={!keyword.trim() || busy} onClick={start}>
            {busy ? "Running…" : "Start Discovery Job"}
          </button>
        </div>
        {error && <div className="error">{error}</div>}
      </div>

      {job && (
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <h2 style={{ margin: 0 }}>
              Job #{job.id} · {job.keyword}
            </h2>
            <span
              className="badge"
              style={{
                background:
                  job.status === "completed"
                    ? "#16a34a"
                    : job.status === "failed"
                      ? "#dc2626"
                      : job.status === "running"
                        ? "#2563eb"
                        : "#6b7280",
              }}
            >
              {job.status}
            </span>
          </div>

          <div className="import-stats" style={{ margin: "12px 0" }}>
            <div className="stat">
              <span className="stat-num">{job.total}</span>
              <span className="stat-label">Total URLs</span>
            </div>
            <div className="stat">
              <span className="stat-num">{job.processed}</span>
              <span className="stat-label">Processed</span>
            </div>
            <div className="stat ok">
              <span className="stat-num">{job.success}</span>
              <span className="stat-label">Success</span>
            </div>
            <div className="stat bad">
              <span className="stat-num">{job.failed}</span>
              <span className="stat-label">Failed</span>
            </div>
            <div className="stat warn">
              <span className="stat-num">{job.skipped}</span>
              <span className="stat-label">Skipped</span>
            </div>
          </div>

          <div className="bar" style={{ width: "100%", marginBottom: 14 }}>
            <span
              style={{
                width: `${pct}%`,
                background: job.status === "failed" ? "#dc2626" : "#2563eb",
              }}
            />
          </div>

          {candidates.length > 0 && (
            <div className="toolbar" style={{ justifyContent: "flex-end", marginBottom: 8 }}>
              <span className="muted" style={{ fontSize: 13 }}>
                {selected.size} selected
              </span>
              <button
                disabled={selected.size === 0 || busy}
                onClick={addSelectedToCrm}
              >
                {busy ? "Adding…" : `+ Add to CRM (${selected.size})`}
              </button>
            </div>
          )}

          <table>
            <thead>
              <tr>
                <th></th>
                <th>Company</th>
                <th>URL</th>
                <th>Score</th>
                <th>Status</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((t) => (
                <tr key={t.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(t.discovery_id!)}
                      onChange={() => toggle(t.discovery_id!)}
                    />
                  </td>
                  <td>{t.company_name ?? "—"}</td>
                  <td className="muted">{t.url}</td>
                  <td>{t.lead_score ?? "—"}</td>
                  <td>
                    <span
                      className="badge"
                      style={{
                        background:
                          t.status === "analyzed"
                            ? "#16a34a"
                            : t.status === "failed"
                              ? "#dc2626"
                              : t.status === "skipped"
                                ? "#d97706"
                                : "#6b7280",
                      }}
                    >
                      {t.status}
                    </span>
                  </td>
                  <td className="muted">{t.error_message ?? "—"}</td>
                </tr>
              ))}
              {candidates.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    No analysed companies yet — start a job to discover prospects.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="card">
        <h2>How it works</h2>
        <div className="muted" style={{ fontSize: 13 }}>
          A job resolves candidate websites from the keyword (search results,
          directories excluded), skips URLs already known to the CRM or prior
          discoveries, and runs the website-analysis pipeline on each. Per-URL
          failures are recorded without aborting the job. Use the checkboxes to
          bulk-add the strongest discoveries to the CRM — the existing
          Lead → Outreach pipeline takes over from there.
        </div>
      </div>
    </div>
  );
}
