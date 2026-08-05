import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { DiscoveryJob, DiscoverySchedule } from "../types";
import { formatDate } from "../utils";

const FREQUENCIES = ["daily", "weekly", "monthly"];

export default function DiscoveryAutomationPage() {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState("");
  const [frequency, setFrequency] = useState("daily");
  const [scoreThr, setScoreThr] = useState(50);
  const [confThr, setConfThr] = useState(40);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [schedules, setSchedules] = useState<DiscoverySchedule[]>([]);
  const [history, setHistory] = useState<Record<number, DiscoveryJob[]>>({});
  const [openHistory, setOpenHistory] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setSchedules(await api.listSchedules());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const wrap = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const create = () =>
    wrap("create", () =>
      api.createSchedule({
        keyword: keyword.trim(),
        frequency,
        lead_score_threshold: scoreThr,
        confidence_threshold: confThr,
      }).then(() => setKeyword("")),
    );

  const toggle = (s: DiscoverySchedule) =>
    wrap("toggle", () => api.updateSchedule(s.id, { enabled: !s.enabled }));

  const runNow = (s: DiscoverySchedule) =>
    wrap("run", async () => {
      await api.runScheduleNow(s.id);
      await refreshHistory(s.id);
    });

  const refreshHistory = async (id: number) => {
    try {
      const jobs = await api.scheduleHistory(id);
      setHistory((prev) => ({ ...prev, [id]: jobs }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const toggleHistory = (s: DiscoverySchedule) => {
    if (openHistory === s.id) {
      setOpenHistory(null);
    } else {
      setOpenHistory(s.id);
      if (!history[s.id]) refreshHistory(s.id);
    }
  };

  const remove = (s: DiscoverySchedule) => {
    if (!confirm(`Delete schedule "${s.keyword}"? History jobs are kept.`)) return;
    wrap("delete", () => api.deleteSchedule(s.id));
  };

  const qualifiedCount = (job: DiscoveryJob) =>
    job.tasks.filter((t) => t.discovery_id != null && t.status === "analyzed").length;

  return (
    <div>
      <h1>Discovery Automation</h1>
      <div className="sub">
        Recurring keyword-driven discovery with automatic qualification: runs
        are executed by the daily scheduler, and discoveries that clear the
        thresholds (lead score, confidence, process + buying signal) are added
        to the CRM automatically.
      </div>

      <div className="card">
        <h2>Create recurring search</h2>
        <div className="toolbar" style={{ flexWrap: "wrap" }}>
          <input
            placeholder='Keyword, e.g. "automotive aluminum die casting supplier Germany"'
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
            style={{ minWidth: 320 }}
          />
          <select value={frequency} onChange={(e) => setFrequency(e.target.value)}>
            {FREQUENCIES.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <label className="muted" style={{ fontSize: 13 }}>
            min lead score{" "}
            <input
              type="number"
              min={0}
              max={100}
              value={scoreThr}
              onChange={(e) => setScoreThr(Number(e.target.value))}
              style={{ width: 64 }}
            />
          </label>
          <label className="muted" style={{ fontSize: 13 }}>
            min confidence{" "}
            <input
              type="number"
              min={0}
              max={100}
              value={confThr}
              onChange={(e) => setConfThr(Number(e.target.value))}
              style={{ width: 64 }}
            />
          </label>
          <button disabled={!keyword.trim() || busy} onClick={create}>
            Create schedule
          </button>
        </div>
        {error && <div className="error">{error}</div>}
      </div>

      {schedules.length === 0 && !busy && (
        <div className="card muted">No schedules yet — create one above.</div>
      )}

      {schedules.map((s) => (
        <div key={s.id} className="card">
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <div>
              <strong>{s.keyword}</strong>
              <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>
                #{s.id} · {s.frequency}
              </span>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span
                className="badge"
                style={{ background: s.enabled ? "#16a34a" : "#6b7280" }}
              >
                {s.enabled ? "enabled" : "disabled"}
              </span>
              <button className="secondary" disabled={busy} onClick={() => toggle(s)}>
                {s.enabled ? "Disable" : "Enable"}
              </button>
              <button className="secondary" disabled={busy || !s.enabled} onClick={() => runNow(s)}>
                Run now
              </button>
              <button className="secondary" onClick={() => toggleHistory(s)}>
                {openHistory === s.id ? "Hide history" : "History"}
              </button>
              <button className="danger" disabled={busy} onClick={() => remove(s)}>
                Delete
              </button>
            </div>
          </div>
          <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
            thresholds: lead score ≥ {s.lead_score_threshold} · confidence ≥{" "}
            {s.confidence_threshold} · last run: {s.last_run ? formatDate(s.last_run) : "never"} ·
            next run: {s.next_run ? formatDate(s.next_run) : "—"}
          </div>

          {openHistory === s.id && (
            <div style={{ marginTop: 12 }}>
              {!history[s.id] ? (
                <div className="spinner">Loading history…</div>
              ) : history[s.id].length === 0 ? (
                <div className="muted">No runs yet.</div>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Job</th>
                      <th>Status</th>
                      <th>Total</th>
                      <th>Success</th>
                      <th>Failed</th>
                      <th>Skipped</th>
                      <th>Qualified</th>
                      <th>Run at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history[s.id].map((j) => (
                      <tr key={j.id}>
                        <td>#{j.id}</td>
                        <td>{j.status}</td>
                        <td>{j.total}</td>
                        <td>{j.success}</td>
                        <td>{j.failed}</td>
                        <td>{j.skipped}</td>
                        <td>
                          <span className="badge" style={{ background: "#16a34a" }}>
                            {qualifiedCount(j)} in CRM
                          </span>
                        </td>
                        <td>{j.created_at ? formatDate(j.created_at) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      ))}

      <div className="card">
        <h2>Qualification rules</h2>
        <div className="muted" style={{ fontSize: 13 }}>
          A discovered company is automatically added to the CRM (as a
          <code> discovery</code>-sourced lead) when ALL of these hold: lead
          score ≥ threshold, confidence ≥ threshold, a manufacturing process
          was detected, and a buying signal exists. Duplicates (website already
          in the CRM / already linked) are never re-created. Qualified leads
          flow into the existing Lead → Outreach pipeline.
        </div>
        <div className="toolbar" style={{ marginTop: 10 }}>
          <button className="secondary" onClick={() => navigate("/discovery/jobs")}>
            → Batch discovery jobs
          </button>
        </div>
      </div>
    </div>
  );
}
