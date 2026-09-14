"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AdminAnalytics, api, authStorage } from "@/lib/api";
import { dueInfo, formatDate, initials } from "@/lib/format";
import Icon from "@/app/components/Icon";

export default function AdminAnalyticsPage() {
  const router = useRouter();
  const [data, setData] = useState<AdminAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!authStorage.isLoggedIn()) { router.push("/login"); return; }
    api.getMe().then((me) => {
      if (me.role !== "admin") { router.push("/dashboard"); return; }
      api.getAdminAnalytics().then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
    }).catch(() => router.push("/login"));
  }, [router]);

  if (loading) {
    return <div style={{ minHeight: "60vh", display: "flex", alignItems: "center", justifyContent: "center" }}><div className="spinner" style={{ width: 22, height: 22, borderTopColor: "var(--accent-primary)", borderColor: "var(--border-card)" }} /></div>;
  }
  if (error || !data) {
    return <div className="app-container"><div className="alert-box alert-error"><Icon name="alert" size={16} />{error || "Could not load analytics."}</div></div>;
  }

  const maxWeekly = Math.max(1, ...data.weeks.map((w) => Math.max(w.meetings, w.tasks_created, w.tasks_completed)));
  const statusTotal = data.status_counts.pending + data.status_counts.in_progress + data.status_counts.done || 1;

  return (
    <div className="app-container">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 14, marginBottom: 22 }}>
        <div>
          <h1 style={{ fontSize: 22, marginBottom: 4 }}>Analytics</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13.5 }}>Meeting volume, task health, and who&apos;s carrying the load.</p>
        </div>
        <Link href="/admin/team" className="btn btn-secondary"><Icon name="users" size={15} /> Team</Link>
      </div>

      <div className="stats-grid" style={{ marginBottom: 20 }}>
        <div className="stat-card">
          <div className="stat-header"><span className="stat-label">Meetings this week</span><Icon name="video" size={14} className="stat-icon" /></div>
          <span className="stat-value">{data.totals.meetings_this_week}</span>
          <div className="stat-subtext">{data.totals.meetings} total</div>
        </div>
        <div className="stat-card">
          <div className="stat-header"><span className="stat-label">Open tasks</span><Icon name="checkSquare" size={14} className="stat-icon" /></div>
          <span className="stat-value">{data.totals.open_tasks}</span>
          <div className="stat-subtext">{data.totals.unassigned_open_tasks} unassigned</div>
        </div>
        <div className="stat-card">
          <div className="stat-header"><span className="stat-label">Overdue</span><Icon name="clock" size={14} className="stat-icon" /></div>
          <span className="stat-value" style={{ color: data.totals.overdue_tasks > 0 ? "var(--accent-rose)" : undefined }}>{data.totals.overdue_tasks}</span>
        </div>
        <div className="stat-card">
          <div className="stat-header"><span className="stat-label">Completion rate</span><Icon name="chart" size={14} className="stat-icon" /></div>
          <span className="stat-value">{data.totals.completion_rate}%</span>
        </div>
      </div>

      <div className="dashboard-zones" style={{ marginBottom: 20 }}>
        <div className="glass-panel">
          <h2 style={{ fontSize: 15, marginBottom: 16 }}>Last 8 weeks</h2>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 10, height: 160 }}>
            {data.weeks.map((week) => (
              <div key={week.week_start} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 120, width: "100%", justifyContent: "center" }}>
                  <div title={`${week.meetings} meetings`} style={{ width: 6, borderRadius: 3, background: "var(--accent-indigo)", height: `${(week.meetings / maxWeekly) * 100}%`, minHeight: 2 }} />
                  <div title={`${week.tasks_created} tasks created`} style={{ width: 6, borderRadius: 3, background: "var(--accent-amber)", height: `${(week.tasks_created / maxWeekly) * 100}%`, minHeight: 2 }} />
                  <div title={`${week.tasks_completed} tasks completed`} style={{ width: 6, borderRadius: 3, background: "var(--accent-emerald)", height: `${(week.tasks_completed / maxWeekly) * 100}%`, minHeight: 2 }} />
                </div>
                <span style={{ fontSize: 9.5, color: "var(--text-dim)" }}>{formatDate(week.week_start)}</span>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 16, marginTop: 14, fontSize: 11.5, color: "var(--text-muted)" }}>
            <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 8, height: 8, borderRadius: 2, background: "var(--accent-indigo)", display: "inline-block" }} /> Meetings</span>
            <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 8, height: 8, borderRadius: 2, background: "var(--accent-amber)", display: "inline-block" }} /> Tasks created</span>
            <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 8, height: 8, borderRadius: 2, background: "var(--accent-emerald)", display: "inline-block" }} /> Tasks completed</span>
          </div>
        </div>

        <div className="glass-panel">
          <h2 style={{ fontSize: 15, marginBottom: 16 }}>Task status</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {([
              ["Pending", data.status_counts.pending, "var(--text-dim)"],
              ["In progress", data.status_counts.in_progress, "var(--accent-amber)"],
              ["Done", data.status_counts.done, "var(--accent-emerald)"],
            ] as [string, number, string][]).map(([label, count, color]) => (
              <div key={label}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, marginBottom: 5 }}>
                  <span style={{ color: "var(--text-secondary)" }}>{label}</span>
                  <span style={{ fontWeight: 700 }}>{count}</span>
                </div>
                <div className="progress-track"><div className="progress-fill" style={{ width: `${(count / statusTotal) * 100}%`, background: color }} /></div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="glass-panel" style={{ marginBottom: 20, padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "18px 20px 12px" }}>
          <h2 style={{ fontSize: 15 }}>Team workload</h2>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr><th>Member</th><th>Meetings owned</th><th>Assigned</th><th>Open</th><th>Overdue</th><th>Done</th><th>Completion</th></tr>
            </thead>
            <tbody>
              {data.workload.map((row) => (
                <tr key={row.user_id}>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span className="avatar" style={{ width: 28, height: 28, fontSize: 11 }}>{initials(row.name)}</span>
                      <div>
                        <div style={{ fontWeight: 600 }}>{row.name}</div>
                        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{row.email}</div>
                      </div>
                    </div>
                  </td>
                  <td>{row.meetings_owned}</td>
                  <td>{row.assigned}</td>
                  <td>{row.open}</td>
                  <td style={{ color: row.overdue > 0 ? "var(--accent-rose)" : undefined, fontWeight: row.overdue > 0 ? 700 : 400 }}>{row.overdue}</td>
                  <td>{row.done}</td>
                  <td>{row.completion_rate === null ? "—" : `${row.completion_rate}%`}</td>
                </tr>
              ))}
              {data.workload.length === 0 && (
                <tr><td colSpan={7} style={{ textAlign: "center", padding: "30px 0", color: "var(--text-muted)" }}>No team members yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="glass-panel">
        <h2 style={{ fontSize: 15, marginBottom: 14 }}>Most overdue</h2>
        {data.overdue.length === 0 ? (
          <div style={{ textAlign: "center", padding: "24px 0", color: "var(--text-muted)", fontSize: 13 }}>Nothing overdue right now.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {data.overdue.map((task) => {
              const due = dueInfo(task);
              return (
                <Link key={task.id} href={`/meetings/${task.meeting_id}`} className="glass-panel-hover" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "11px 13px", borderRadius: "var(--radius-sm)", background: "var(--bg-subtle)", border: "1px solid var(--border-subtle)" }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>{task.task}</div>
                    <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{task.assignee || "Unassigned"} · {task.meeting_title}</div>
                  </div>
                  <span className={`due-badge due-${due.tone}`}><Icon name="clock" size={12} />{due.label}</span>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
