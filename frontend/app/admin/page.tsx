"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { ActionItem, AdminAnalytics, Meeting, api, authStorage } from "@/lib/api";
import { dueInfo, formatDateTime, greeting, initials, platformLabel } from "@/lib/format";
import Icon from "@/app/components/Icon";
import InviteEmployeeModal from "@/app/components/InviteEmployeeModal";
import AskAlinaPanel from "@/app/components/AskAlinaPanel";

export default function AdminHomePage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<{ full_name?: string | null; email?: string } | null>(null);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [tasks, setTasks] = useState<ActionItem[]>([]);
  const [analytics, setAnalytics] = useState<AdminAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [showAddModal, setShowAddModal] = useState(false);
  const [taskFilter, setTaskFilter] = useState<"all" | "unassigned" | "overdue">("all");

  useEffect(() => {
    if (!authStorage.isLoggedIn()) { router.push("/login"); return; }
    api.getMe().then((me) => {
      if (me.role !== "admin") { router.push("/dashboard"); return; }
      setCurrentUser(me);
      load();
    }).catch(() => router.push("/login"));
  }, [router]);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [meetingsData, tasksData, analyticsData] = await Promise.all([
        api.getMeetings(),
        api.getAllTasks(),
        api.getAdminAnalytics().catch(() => null),
      ]);
      setMeetings(meetingsData);
      setTasks(tasksData);
      setAnalytics(analyticsData);
    } catch (err: any) {
      setError(err?.message || "Failed to load the admin overview");
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="app-container" style={{ textAlign: "center", padding: "120px 0" }}>
        <div className="spinner" style={{ margin: "0 auto 16px", width: 22, height: 22, borderTopColor: "var(--accent-primary)", borderColor: "var(--border-card)" }} />
        <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>Loading the admin overview…</p>
      </div>
    );
  }

  const openTasks = tasks.filter((t) => t.status !== "done");
  const visibleTasks = (
    taskFilter === "unassigned" ? openTasks.filter((t) => !t.assignee_user_id) :
    taskFilter === "overdue" ? openTasks.filter((t) => t.is_overdue) :
    openTasks
  ).slice(0, 12);

  return (
    <div className="app-container">
      <div className="hero-banner">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 20 }}>
          <div>
            <span className="eyebrow"><Icon name="briefcase" size={12} /> Admin overview</span>
            <h1 style={{ fontSize: "clamp(22px, 3vw, 28px)", margin: "8px 0 6px" }}>
              {greeting()}{currentUser?.full_name ? `, ${currentUser.full_name.split(" ")[0]}` : ""}.
            </h1>
            <p style={{ color: "var(--text-secondary)", fontSize: 13.5, maxWidth: 560 }}>
              Every meeting, every task, and who it&apos;s assigned to — across the whole workspace.
            </p>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Link href="/admin/analytics" className="btn btn-secondary"><Icon name="activity" size={15} /> Analytics</Link>
            <Link href="/admin/settings" className="btn btn-secondary"><Icon name="settings" size={15} /> Settings</Link>
            <button onClick={() => setShowAddModal(true)} className="btn btn-primary"><Icon name="plus" size={15} /> Add employee</button>
          </div>
        </div>
      </div>

      {error && <div className="alert-box alert-error"><Icon name="alert" size={16} />{error}</div>}
      {success && <div className="alert-box alert-success"><Icon name="check" size={16} />{success}</div>}

      <div className="ledger-strip">
        <div className="ledger-cell ledger-cell-indigo">
          <div className="stat-header"><span className="stat-label">Team</span><span className="stat-icon-badge"><Icon name="users" size={14} /></span></div>
          <span className="stat-value">{analytics?.totals.members ?? "—"}</span>
          <div className="stat-subtext">registered members</div>
        </div>
        <div className="ledger-cell ledger-cell-cyan">
          <div className="stat-header"><span className="stat-label">Meetings</span><span className="stat-icon-badge"><Icon name="video" size={14} /></span></div>
          <span className="stat-value">{meetings.length}</span>
          <div className="stat-subtext">{analytics?.totals.meetings_this_week ?? 0} this week</div>
        </div>
        <div className="ledger-cell ledger-cell-amber">
          <div className="stat-header"><span className="stat-label">Open tasks</span><span className="stat-icon-badge"><Icon name="checkSquare" size={14} /></span></div>
          <span className="stat-value">{openTasks.length}</span>
          <div className="stat-subtext">{analytics?.totals.unassigned_open_tasks ?? 0} unassigned</div>
        </div>
        <div className="ledger-cell ledger-cell-rose">
          <div className="stat-header"><span className="stat-label">Overdue</span><span className="stat-icon-badge"><Icon name="clock" size={14} /></span></div>
          <span className="stat-value" style={{ color: (analytics?.totals.overdue_tasks ?? 0) > 0 ? "var(--accent-rose)" : undefined }}>{analytics?.totals.overdue_tasks ?? 0}</span>
          <div className="stat-subtext">need chasing</div>
        </div>
      </div>

      <div className="dashboard-zones">
        <div className="glass-panel">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, paddingBottom: 12, borderBottom: "1px solid var(--border-subtle)" }}>
            <div>
              <h2 style={{ fontSize: 16 }}>Recent meetings</h2>
              <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Across the whole workspace</span>
            </div>
            <Link href="/meetings" className="btn btn-secondary btn-sm">View all <Icon name="arrowRight" size={13} /></Link>
          </div>
          {meetings.length === 0 ? (
            <div className="empty-state"><div className="icon-wrap"><Icon name="video" size={20} /></div><h4>No meetings yet</h4></div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {meetings.slice(0, 6).map((m) => (
                <Link key={m.id} href={`/meetings/${m.id}`} className="glass-panel-hover" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 14px", borderRadius: "var(--radius-md)", background: "var(--bg-subtle)", border: "1px solid var(--border-subtle)" }}>
                  <div style={{ minWidth: 0, paddingRight: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
                      <span className="badge badge-cyan">{platformLabel(m.platform)}</span>
                      <h4 style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.title}</h4>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{formatDateTime(m.created_at)}</div>
                  </div>
                  <Icon name="chevronRight" size={14} />
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="glass-panel">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, paddingBottom: 12, borderBottom: "1px solid var(--border-subtle)" }}>
            <h2 style={{ fontSize: 16 }}>Team snapshot</h2>
            <Link href="/admin/team" className="btn btn-secondary btn-sm">Manage <Icon name="arrowRight" size={13} /></Link>
          </div>
          {analytics && analytics.workload.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              {analytics.workload.slice(0, 6).map((row) => (
                <div key={row.user_id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 10px", borderRadius: "var(--radius-sm)", background: "var(--bg-subtle)" }}>
                  <span className="avatar" style={{ width: 28, height: 28, fontSize: 11 }}>{initials(row.name)}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.name}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{row.open} open{row.overdue > 0 ? ` · ${row.overdue} overdue` : ""}</div>
                  </div>
                  {row.overdue > 0 && <span className="badge badge-rose">{row.overdue}</span>}
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state" style={{ padding: "30px 0" }}><p>No team activity yet.</p></div>
          )}
        </div>

        <AskAlinaPanel />

        <div className="glass-panel dashboard-tasks">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, paddingBottom: 12, borderBottom: "1px solid var(--border-subtle)", flexWrap: "wrap", gap: 10 }}>
            <div>
              <h2 style={{ fontSize: 16 }}>Who has what</h2>
              <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Every open task and its assignee</span>
            </div>
            <div className="mode-toggle" style={{ margin: 0 }}>
              <button className={taskFilter === "all" ? "is-on" : ""} onClick={() => setTaskFilter("all")}>All ({openTasks.length})</button>
              <button className={taskFilter === "unassigned" ? "is-on" : ""} onClick={() => setTaskFilter("unassigned")}>Unassigned ({openTasks.filter((t) => !t.assignee_user_id).length})</button>
              <button className={taskFilter === "overdue" ? "is-on" : ""} onClick={() => setTaskFilter("overdue")}>Overdue ({openTasks.filter((t) => t.is_overdue).length})</button>
            </div>
          </div>

          {visibleTasks.length === 0 ? (
            <div className="empty-state"><div className="icon-wrap"><Icon name="checkSquare" size={20} /></div><h4>Nothing to show</h4></div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr><th>Task</th><th>Assigned to</th><th>Meeting</th><th>Deadline</th><th>Priority</th></tr>
                </thead>
                <tbody>
                  {visibleTasks.map((t) => {
                    const due = dueInfo(t);
                    return (
                      <tr key={t.id} className="clickable" onClick={() => router.push(`/meetings/${t.meeting_id}`)}>
                        <td style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.task}</td>
                        <td>
                          {t.assignee ? (
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                              <span className="avatar" style={{ width: 20, height: 20, fontSize: 9 }}>{initials(t.assignee)}</span>
                              {t.assignee}
                            </span>
                          ) : <span className="badge badge-amber">Unassigned</span>}
                        </td>
                        <td style={{ color: "var(--text-muted)", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.meeting_title}</td>
                        <td>{(t.due_at || t.deadline) ? <span className={`due-badge due-${due.tone}`}><Icon name="clock" size={11} />{due.label}</span> : <span style={{ color: "var(--text-dim)" }}>—</span>}</td>
                        <td><span className={`priority-dot priority-dot-${t.priority}`} title={`${t.priority} priority`} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {showAddModal && (
        <InviteEmployeeModal
          onClose={() => setShowAddModal(false)}
          onInvited={() => { setSuccess("Invite sent."); load(); }}
          allowRoleChoice={false}
        />
      )}
    </div>
  );
}
