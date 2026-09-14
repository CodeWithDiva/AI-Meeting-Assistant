"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { ActionItem, api, authStorage, DashboardStats, Meeting } from "@/lib/api";
import { detectPlatform, dueInfo, formatDateTime, greeting, platformLabel } from "@/lib/format";
import Icon from "@/app/components/Icon";
import AskAlinaPanel from "@/app/components/AskAlinaPanel";

export default function DashboardPage() {
  const router = useRouter();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [tasks, setTasks] = useState<ActionItem[]>([]);
  const [currentUser, setCurrentUser] = useState<{ full_name?: string | null; email?: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showModal, setShowModal] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newPlatform, setNewPlatform] = useState("zoom");
  const [creating, setCreating] = useState(false);

  // "Paste a link, the assistant joins"
  const [joinLink, setJoinLink] = useState("");
  const [joinTitle, setJoinTitle] = useState("");
  const [joinRecord, setJoinRecord] = useState(false);
  const [joinMode, setJoinMode] = useState<"agent" | "attach">("agent");
  const [joinDisplayName, setJoinDisplayName] = useState("");
  const [joining, setJoining] = useState(false);
  const [joinMessage, setJoinMessage] = useState("");

  useEffect(() => {
    if (!authStorage.isLoggedIn()) {
      router.push("/login");
      return;
    }
    api.getMe().then((me) => {
      if (me.role === "admin") { router.push("/admin"); return; }
      setCurrentUser(me);
      loadDashboardData();
    }).catch(() => router.push("/login"));
  }, [router]);

  async function loadDashboardData() {
    setLoading(true);
    setError("");
    try {
      const [statsData, meetingsData, tasksData] = await Promise.all([
        api.getDashboardStats().catch(
          () => ({
            total_meetings: 0, total_tasks: 0, pending_tasks: 0, in_progress_tasks: 0,
            done_tasks: 0, recent_meetings: 0, overdue_tasks: 0, due_soon_tasks: 0,
            my_open_tasks: 0, completion_rate: 0,
          } as DashboardStats)
        ),
        api.getMeetings().catch(() => []),
        api.getAllTasks().catch(() => []),
      ]);
      setStats(statsData);
      setMeetings(meetingsData);
      setTasks(tasksData);
    } catch (err: any) {
      setError(err?.message || "Failed to load dashboard data");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateMeeting(e: FormEvent) {
    e.preventDefault();
    if (!newTitle.trim()) return;
    setCreating(true);
    try {
      const created = await api.createMeeting(newTitle.trim(), newPlatform);
      setShowModal(false);
      setNewTitle("");
      router.push(`/meetings/${created.id}`);
    } catch (err: any) {
      setError(err?.message || "Could not create meeting");
    } finally {
      setCreating(false);
    }
  }

  async function handleSendAssistant(e: FormEvent) {
    e.preventDefault();
    if (joining) return;
    if (joinMode === "agent" && !joinLink.trim()) {
      setError("Bot ko join karwane ke liye Zoom ya Google Meet ka link chahiye. Ya 'I'll join' mode chunein.");
      return;
    }
    if (joinMode === "agent" && !detectPlatform(joinLink)) {
      setError("Ye link Zoom ya Google Meet ka nahi lag raha. Poora meeting link paste karein.");
      return;
    }
    if (joinMode === "attach" && !joinLink.trim() && !joinTitle.trim()) {
      setError("Meeting ka title likhein (attach mode me link optional hai).");
      return;
    }

    setJoining(true);
    setError("");
    setJoinMessage("");
    try {
      const result = await api.sendAgentToMeeting(joinLink.trim(), {
        title: joinTitle.trim() || undefined,
        record: joinRecord,
        mode: joinMode,
        displayName: joinMode === "attach" ? joinDisplayName.trim() || undefined : undefined,
      });
      setJoinLink("");
      setJoinTitle("");
      setJoinMessage(result.message);
      router.push(`/meetings/${result.meeting_id}`);
    } catch (err: any) {
      setError(err?.message || "Could not send the assistant to that meeting.");
    } finally {
      setJoining(false);
    }
  }

  async function handleToggleTask(taskId: number, currentStatus: string) {
    const nextStatus = currentStatus === "done" ? "pending" : "done";
    try {
      await api.updateTask(taskId, { status: nextStatus });
      const [updatedTasks, updatedStats] = await Promise.all([api.getAllTasks(), api.getDashboardStats()]);
      setTasks(updatedTasks);
      setStats(updatedStats);
    } catch (err: any) {
      setError(err?.message || "Failed to update task status");
    }
  }

  const pendingTasks = tasks.filter((t) => t.status === "pending");
  const inProgressTasks = tasks.filter((t) => t.status === "in_progress");
  const doneTasks = tasks.filter((t) => t.status === "done");
  const detectedPlatform = detectPlatform(joinLink);

  function meetingState(meeting: Meeting) {
    if (!meeting.transcript) return { label: "Scheduled", badge: "badge-amber" };
    if (meeting.ended_at) return { label: "Done", badge: "badge-emerald" };
    return { label: "Live", badge: "badge-cyan" };
  }

  if (loading) {
    return (
      <div className="app-container" style={{ textAlign: "center", padding: "120px 0" }}>
        <div className="spinner" style={{ margin: "0 auto 16px", width: 22, height: 22, borderTopColor: "var(--accent-primary)", borderColor: "var(--border-card)" }} />
        <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>Loading your workspace…</p>
      </div>
    );
  }

  return (
    <div className="app-container">
      <div className="hero-banner">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 20 }}>
          <div>
            <span className="eyebrow">My workspace</span>
            <h1 style={{ fontSize: "clamp(22px, 3vw, 28px)", margin: "8px 0 6px" }}>
              {greeting()}{currentUser?.full_name ? `, ${currentUser.full_name.split(" ")[0]}` : ""}.
            </h1>
            <p style={{ color: "var(--text-secondary)", fontSize: 13.5, maxWidth: 560 }}>
              Review your meetings and keep your assigned tasks moving.
            </p>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Link href="/tasks" className="btn btn-secondary"><Icon name="checkSquare" size={15} /> My tasks</Link>
            <button onClick={() => setShowModal(true)} className="btn btn-primary"><Icon name="plus" size={15} /> New meeting</button>
          </div>
        </div>
      </div>

      {error && <div className="alert-box alert-error"><Icon name="alert" size={16} />{error}</div>}
      {joinMessage && <div className="alert-box alert-success"><Icon name="check" size={16} />{joinMessage}</div>}

      <div className="launch-card">
        <span className="eyebrow"><Icon name="radio" size={12} /> Meeting assistant</span>
        <h2>Send the assistant to a meeting</h2>

        <div className="mode-toggle" role="tablist" aria-label="How the assistant joins">
          <button type="button" role="tab" aria-selected={joinMode === "agent"} className={joinMode === "agent" ? "is-on" : ""} onClick={() => setJoinMode("agent")} disabled={joining}>
            Assistant joins as a participant
          </button>
          <button type="button" role="tab" aria-selected={joinMode === "attach"} className={joinMode === "attach" ? "is-on" : ""} onClick={() => setJoinMode("attach")} disabled={joining}>
            I&apos;ll join — assistant just listens
          </button>
        </div>

        <p className="launch-sub">
          {joinMode === "agent" ? (
            <>Paste a Zoom or Google Meet link. The assistant opens its own browser, joins the call by
            name, and transcribes Urdu, English and Roman Urdu live.</>
          ) : (
            <>You join in your normal Zoom/Meet app. The assistant only listens through your audio
            device — it still writes notes, decisions and tasks. Needs the virtual audio cable (see
            <code style={{ margin: "0 4px" }}>docs/browser-bot-setup.md</code>).</>
          )}
        </p>

        <form onSubmit={handleSendAssistant} className="launch-row">
          <div style={{ flex: 1, minWidth: 220, position: "relative" }}>
            <input
              type="text"
              className="form-input"
              placeholder={joinMode === "agent" ? "https://zoom.us/j/1234567890  ·  https://meet.google.com/abc-defg-hij" : "Meeting link (optional — only used for the title)"}
              value={joinLink}
              onChange={(e) => setJoinLink(e.target.value)}
              disabled={joining}
              aria-label="Meeting link"
            />
            {joinMode === "agent" && detectedPlatform && (
              <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)" }}>
                {detectedPlatform === "zoom" ? <span className="badge badge-cyan">Zoom</span> : <span className="badge badge-emerald">Google Meet</span>}
              </span>
            )}
          </div>
          <input
            type="text"
            className="form-input"
            style={{ flex: "0 1 200px", minWidth: 160 }}
            placeholder={joinMode === "attach" ? "Title (required)" : "Title (optional)"}
            value={joinTitle}
            onChange={(e) => setJoinTitle(e.target.value)}
            disabled={joining}
            aria-label="Meeting title"
          />
          {joinMode === "attach" && (
            <input
              type="text"
              className="form-input"
              style={{ flex: "0 1 160px", minWidth: 140 }}
              placeholder="Your name"
              value={joinDisplayName}
              onChange={(e) => setJoinDisplayName(e.target.value)}
              disabled={joining}
              aria-label="Your name"
            />
          )}
          <button type="submit" className="btn btn-primary btn-lg" disabled={joining}>
            {joining ? <span style={{ display: "flex", alignItems: "center", gap: 8 }}><span className="spinner" /> Sending…</span> : <>{joinMode === "agent" ? "Join meeting" : "Start listening"}</>}
          </button>
        </form>

        <label className="launch-consent">
          <input type="checkbox" checked={joinRecord} onChange={(e) => setJoinRecord(e.target.checked)} disabled={joining} />
          <span>Record the audio to disk — off by default. Tell participants before turning this on.</span>
        </label>
      </div>

      <div className="ledger-strip">
        <div className="ledger-cell">
          <div className="stat-header"><span className="stat-label">My meetings</span><Icon name="video" size={14} className="stat-icon" /></div>
          <span className="stat-value">{stats?.total_meetings ?? meetings.length}</span>
          <div className="stat-subtext">{stats?.recent_meetings ?? 0} this week</div>
        </div>
        <div className="ledger-cell">
          <div className="stat-header"><span className="stat-label">Open tasks</span><Icon name="checkSquare" size={14} className="stat-icon" /></div>
          <span className="stat-value">{pendingTasks.length + inProgressTasks.length}</span>
          <div className="stat-subtext">{stats?.my_open_tasks ?? 0} assigned to you</div>
        </div>
        <div className="ledger-cell">
          <div className="stat-header"><span className="stat-label">Due soon / overdue</span><Icon name="clock" size={14} className="stat-icon" /></div>
          <span className="stat-value" style={{ color: (stats?.overdue_tasks ?? 0) > 0 ? "var(--accent-rose)" : undefined }}>
            {(stats?.due_soon_tasks ?? 0) + (stats?.overdue_tasks ?? 0)}
          </span>
          <div className="stat-subtext">{stats?.overdue_tasks ?? 0} overdue</div>
        </div>
        <div className="ledger-cell">
          <div className="stat-header"><span className="stat-label">Completion rate</span><Icon name="chart" size={14} className="stat-icon" /></div>
          <span className="stat-value">{stats?.completion_rate ?? 0}%</span>
          <div className="progress-track" style={{ marginTop: 8 }}><div className="progress-fill" style={{ width: `${stats?.completion_rate ?? 0}%` }} /></div>
        </div>
      </div>

      <div className="dashboard-zones">
        <div className="glass-panel">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18, paddingBottom: 12, borderBottom: "1px solid var(--border-subtle)" }}>
            <div>
              <h2 style={{ fontSize: 16 }}>My meetings</h2>
              <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Every session, its state, and what happens next</span>
            </div>
            <Link href="/meetings" className="btn btn-secondary btn-sm">View all <Icon name="arrowRight" size={13} /></Link>
          </div>

          {meetings.length === 0 ? (
            <div className="empty-state">
              <div className="icon-wrap"><Icon name="video" size={20} /></div>
              <h4>No meetings yet</h4>
              <p>Paste a link above, or create one manually.</p>
              <button onClick={() => setShowModal(true)} className="btn btn-secondary btn-sm">Create a meeting</button>
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
              {meetings.slice(0, 6).map((m) => (
                <Link key={m.id} href={`/meetings/${m.id}`} className="glass-panel-hover" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "13px 15px", borderRadius: "var(--radius-md)", background: "var(--bg-subtle)", border: "1px solid var(--border-subtle)" }}>
                  <div style={{ flex: 1, minWidth: 0, paddingRight: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      <span className={`badge ${meetingState(m).badge}`}>{meetingState(m).label}</span>
                      <h4 style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.title}</h4>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{platformLabel(m.platform)} · {formatDateTime(m.created_at)}</div>
                  </div>
                  <Icon name="chevronRight" size={15} />
                </Link>
              ))}
            </div>
          )}
        </div>

        <AskAlinaPanel />

        <div id="tasks" className="glass-panel dashboard-tasks">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18, paddingBottom: 12, borderBottom: "1px solid var(--border-subtle)" }}>
            <div>
              <h2 style={{ fontSize: 16 }}>My tasks</h2>
              <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Pending, in progress, and done</span>
            </div>
            <Link href="/tasks" className="badge badge-indigo">{pendingTasks.length} pending</Link>
          </div>

          {tasks.length === 0 ? (
            <div className="empty-state">
              <div className="icon-wrap"><Icon name="checkSquare" size={20} /></div>
              <h4>Nothing here yet</h4>
              <p>Tasks assigned to you in a meeting will show up here.</p>
            </div>
          ) : (
            <div className="task-columns">
              {([["Pending", pendingTasks], ["In progress", inProgressTasks], ["Done", doneTasks]] as [string, ActionItem[]][]).map(([label, columnTasks]) => (
                <div className="task-column" key={label}>
                  <div className="task-column-title">{label} <span>{columnTasks.length}</span></div>
                  {columnTasks.slice(0, 4).map((t) => {
                    const due = dueInfo(t);
                    return (
                      <div key={t.id} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "12px 13px", borderRadius: "var(--radius-sm)", background: "var(--bg-subtle)", border: "1px solid var(--border-subtle)", marginBottom: 8 }}>
                        <input type="checkbox" checked={t.status === "done"} onChange={() => handleToggleTask(t.id, t.status)} style={{ marginTop: 3, cursor: "pointer", accentColor: "var(--accent-primary)" }} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <p style={{ fontSize: 13, fontWeight: 500, marginBottom: 5, lineHeight: 1.4, textDecoration: t.status === "done" ? "line-through" : "none", color: t.status === "done" ? "var(--text-muted)" : "var(--text-primary)" }}>{t.task}</p>
                          <div style={{ display: "flex", gap: 8, fontSize: 11.5, color: "var(--text-muted)", flexWrap: "wrap", alignItems: "center" }}>
                            <span className={`priority-dot priority-dot-${t.priority}`} title={`${t.priority} priority`} />
                            {t.meeting_title && <span>{t.meeting_title}</span>}
                            {t.due_at || t.deadline ? <span className={`due-badge due-${due.tone}`}><Icon name="clock" size={11} />{due.label}</span> : null}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {showModal && (
        <div className="modal-backdrop" onClick={() => setShowModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <h3 style={{ fontSize: 17 }}>Create a meeting</h3>
              <button onClick={() => setShowModal(false)} className="icon-btn" style={{ border: "none" }}><Icon name="x" size={16} /></button>
            </div>
            <form onSubmit={handleCreateMeeting}>
              <div className="form-group">
                <label className="form-label">Meeting title</label>
                <input type="text" className="form-input" placeholder="e.g. Q3 sprint planning" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} autoFocus required />
              </div>
              <div className="form-group" style={{ marginBottom: 22 }}>
                <label className="form-label">Platform</label>
                <select className="form-input" value={newPlatform} onChange={(e) => setNewPlatform(e.target.value)}>
                  <option value="zoom">Zoom</option>
                  <option value="google_meet">Google Meet</option>
                  <option value="in_person">In person / audio upload</option>
                </select>
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowModal(false)} disabled={creating}>Cancel</button>
                <button type="submit" className="btn btn-primary btn-sm" disabled={creating || !newTitle.trim()}>{creating ? "Creating…" : "Create"}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
