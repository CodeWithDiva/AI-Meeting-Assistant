"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { ActionItem, api, authStorage, DashboardStats, Meeting } from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [tasks, setTasks] = useState<ActionItem[]>([]);
  const [currentUser, setCurrentUser] = useState<{ role?: string; full_name?: string | null; email?: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showModal, setShowModal] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newPlatform, setNewPlatform] = useState("zoom");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!authStorage.isLoggedIn()) {
      router.push("/login");
      return;
    }
    loadDashboardData();
  }, [router]);

  async function loadDashboardData() {
    setLoading(true);
    setError("");
    try {
      const [statsData, meetingsData, tasksData, userData] = await Promise.all([
        api.getDashboardStats().catch(() => ({
          total_meetings: 0,
          total_tasks: 0,
          pending_tasks: 0,
          done_tasks: 0,
          recent_meetings: 0,
        })),
        api.getMeetings().catch(() => []),
        api.getAllTasks().catch(() => []),
        api.getMe().catch(() => null),
      ]);

      setStats(statsData);
      setMeetings(meetingsData);
      setTasks(tasksData);
      setCurrentUser(userData);
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

  async function handleToggleTask(taskId: number, currentStatus: string) {
    const nextStatus = currentStatus === "done" ? "pending" : "done";
    try {
      await api.updateTask(taskId, { status: nextStatus });
      const [updatedTasks, updatedStats] = await Promise.all([
        api.getAllTasks(),
        api.getDashboardStats(),
      ]);
      setTasks(updatedTasks);
      setStats(updatedStats);
    } catch (err: any) {
      setError(err?.message || "Failed to update task status");
    }
  }

  function getPlatformBadge(platform?: string | null) {
    const p = (platform || "direct").toLowerCase();
    if (p.includes("zoom")) return <span className="badge badge-cyan">📹 Zoom</span>;
    if (p.includes("meet")) return <span className="badge badge-emerald">🟢 Meet</span>;
    if (p.includes("team")) return <span className="badge badge-purple">🟣 Teams</span>;
    return <span className="badge badge-indigo">🎙️ Direct Audio</span>;
  }

  const isAdmin = currentUser?.role === "admin";
  const pendingTasks = tasks.filter((task) => task.status === "pending");
  const inProgressTasks = tasks.filter((task) => task.status === "in_progress");
  const doneTasks = tasks.filter((task) => task.status === "done");

  function getMeetingState(meeting: Meeting) {
    if (!meeting.transcript) return { label: "Scheduled", badge: "badge-amber" };
    if (meeting.ended_at) return { label: "Done", badge: "badge-emerald" };
    return { label: "Live", badge: "badge-cyan" };
  }

  if (loading) {
    return (
      <div className="app-container" style={{ textAlign: "center", padding: "120px 0" }}>
        <div className="spinner" style={{ margin: "0 auto 16px", width: 28, height: 28, borderWidth: 3 }}></div>
        <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>Connecting to AI Meeting Core...</p>
      </div>
    );
  }

  return (
    <div className="app-container">
      {/* Product header */}
      <div className="hero-banner">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 20 }}>
          <div>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <span className="badge badge-indigo">{isAdmin ? "HOST WORKSPACE" : "MY WORKSPACE"}</span>
              <span style={{ color: "var(--text-muted)", fontSize: 13 }}>•</span>
              <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>Faster-Whisper STT + Local LLM Core</span>
            </div>
              <h1 style={{ fontSize: "clamp(24px, 3.5vw, 36px)", lineHeight: 1.2, marginBottom: 8 }}>
              {isAdmin ? "Good morning. Here is your meeting ledger." : "Your work, distilled from every meeting."}
            </h1>
            <p style={{ color: "var(--text-secondary)", fontSize: 14, maxWidth: 620, lineHeight: 1.6 }}>
              {isAdmin ? "A clear view of meetings, actions, and the people moving work forward." : "Review your meetings and keep assigned actions moving."}
            </p>
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            <Link href="/tasks" className="btn btn-secondary btn-lg">
              <span>📋</span>
              <span>My Tasks</span>
            </Link>
            {isAdmin && (
              <>
                <Link href="/admin/team" className="btn btn-secondary btn-lg">
                  <span>👥</span>
                  <span>Team</span>
                </Link>
                <Link href="/admin/settings" className="btn btn-secondary btn-lg">
                  <span>⚙️</span>
                  <span>Settings</span>
                </Link>
              </>
            )}
            <button onClick={() => setShowModal(true)} className="btn btn-primary btn-lg">
              <span>+</span>
              <span>New Meeting Session</span>
            </button>
          </div>
        </div>
      </div>

      {error && <div className="alert-box alert-error">{error}</div>}

      {/* Ledger Strip */}
      <div className="ledger-strip">
        <div className="ledger-cell">
          <div className="stat-header">
            <span className="stat-label">Total Meetings</span>
          </div>
          <span className="stat-value">{stats?.total_meetings ?? meetings.length}</span>
          <div className="stat-subtext">All time</div>
        </div>
        <div className="ledger-cell">
          <div className="stat-header">
            <span className="stat-label">This Week</span>
          </div>
          <span className="stat-value">{stats?.recent_meetings ?? Math.min(meetings.length, 5)}</span>
          <div className="stat-subtext">Recent sessions</div>
        </div>
        <div className="ledger-cell">
          <div className="stat-header">
            <span className="stat-label">Pending Tasks</span>
          </div>
          <span className="stat-value">{stats?.pending_tasks ?? pendingTasks.length}</span>
          <div className="stat-subtext">Needs attention</div>
        </div>
        <div className="ledger-cell">
          <div className="stat-header">
            <span className="stat-label">Team Active Now</span>
          </div>
          <span className="stat-value">{isAdmin ? "—" : "1"}</span>
          <div className="stat-subtext">Live presence coming soon</div>
        </div>
      </div>

      {/* Main Content Grid */}
      <div className="dashboard-zones">
        {/* Recent Meetings */}
        <div className="glass-panel">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 20,
              paddingBottom: 12,
              borderBottom: "1px solid var(--border-subtle)",
            }}
          >
            <div>
              <h2 style={{ fontSize: 18, marginBottom: 2 }}>{isAdmin ? "Recent Meetings" : "My Meetings"}</h2>
              <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Every session, its state, and what happens next</span>
            </div>
            <Link href="/meetings" className="btn btn-secondary btn-sm">
              View All ({meetings.length}) →
            </Link>
          </div>

          {meetings.length === 0 ? (
            <div style={{ textAlign: "center", padding: "50px 20px", color: "var(--text-muted)", fontSize: 14 }}>
              <p style={{ marginBottom: 14 }}>No meetings recorded yet.</p>
              <button onClick={() => setShowModal(true)} className="btn btn-secondary btn-sm">
                Create First Meeting
              </button>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {meetings.slice(0, 5).map((m) => (
                <Link
                  key={m.id}
                  href={`/meetings/${m.id}`}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "14px 16px",
                    borderRadius: "var(--radius-sm)",
                    background: "var(--bg-input)",
                    border: "1px solid var(--border-subtle)",
                    transition: "all 0.15s ease",
                  }}
                  className="glass-panel-hover"
                >
                  <div style={{ flex: 1, minWidth: 0, paddingRight: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      <span className={`badge ${getMeetingState(m).badge}`}>{getMeetingState(m).label}</span>
                      {getPlatformBadge(m.platform)}
                      <h4 style={{ fontSize: 15, fontWeight: 600, color: "var(--text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {m.title}
                      </h4>
                    </div>
                    <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                      {m.created_at ? new Date(m.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "Recent"}
                    </div>
                  </div>

                  <div>
                    {m.transcript ? (
                      <span className="badge badge-emerald">Transcribed</span>
                    ) : (
                      <span className="badge badge-amber">Awaiting Audio</span>
                    )}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="glass-panel ask-ai-panel">
          <span className="eyebrow">MEETING MEMORY</span>
          <h2 style={{ fontSize: 20, margin: "8px 0" }}>Ask about a meeting</h2>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, lineHeight: 1.55, marginBottom: 20 }}>
            Open a meeting to ask grounded questions about its transcript, decisions, and action items.
          </p>
          <Link href="/meetings" className="btn btn-primary" style={{ width: "100%" }}>Browse meeting memory</Link>
          <div className="ask-ai-note">Cross-meeting search will appear here when workspace memory is connected.</div>
        </div>

        {/* Action Items Board */}
        <div id="tasks" className="glass-panel dashboard-tasks">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 20,
              paddingBottom: 12,
              borderBottom: "1px solid var(--border-subtle)",
            }}
          >
            <div>
              <h2 style={{ fontSize: 18, marginBottom: 2 }}>{isAdmin ? "Action items" : "My Tasks"}</h2>
              <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Pending, in progress, and done</span>
            </div>
            <span className="badge badge-indigo">{pendingTasks.length} Pending</span>
          </div>

          {tasks.length === 0 ? (
            <div style={{ textAlign: "center", padding: "50px 20px", color: "var(--text-muted)", fontSize: 14 }}>
              <p>🎉 All action items have been completed or no tasks yet.</p>
            </div>
          ) : (
            <div className="task-columns">
              {[
                ["Pending", pendingTasks],
                ["In Progress", inProgressTasks],
                ["Done", doneTasks],
              ].map(([label, columnTasks]) => (
                <div className="task-column" key={label as string}>
                  <div className="task-column-title">{label as string} <span>{(columnTasks as ActionItem[]).length}</span></div>
                  {(columnTasks as ActionItem[]).slice(0, 4).map((t) => (
                <div
                  key={t.id}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 12,
                    padding: "14px 16px",
                    borderRadius: "var(--radius-sm)",
                    background: "var(--bg-input)",
                    border: "1px solid var(--border-subtle)",
                    transition: "all 0.15s ease",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={t.status === "done"}
                    onChange={() => handleToggleTask(t.id, t.status)}
                    style={{
                      marginTop: 3,
                      cursor: "pointer",
                      width: 16,
                      height: 16,
                      accentColor: "var(--accent-indigo)",
                    }}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ fontSize: 14, fontWeight: 500, marginBottom: 4, lineHeight: 1.4, color: "var(--text-primary)" }}>
                      {t.task}
                    </p>
                    <div style={{ display: "flex", gap: 10, fontSize: 12, color: "var(--text-muted)", flexWrap: "wrap" }}>
                      {t.assignee && (
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "#a5b4fc" }}>
                          👤 {t.assignee}
                        </span>
                      )}
                      {t.deadline && (
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "#fde047" }}>
                          ⏰ Due: {t.deadline}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* New Meeting Modal */}
      {showModal && (
        <div className="modal-backdrop" onClick={() => setShowModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <h3 style={{ fontSize: 20 }}>Create New Meeting</h3>
              <button
                onClick={() => setShowModal(false)}
                style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: 18 }}
              >
                ✕
              </button>
            </div>
            <p style={{ color: "var(--text-secondary)", fontSize: 13, marginBottom: 22 }}>
              Configure meeting session details for autonomous recording and notes generation.
            </p>

            <form onSubmit={handleCreateMeeting}>
              <div className="form-group">
                <label className="form-label">Meeting Title</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="e.g. Q3 Sprint Architecture & Planning"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  autoFocus
                  required
                />
              </div>

              <div className="form-group" style={{ marginBottom: 24 }}>
                <label className="form-label">Platform / Integration</label>
                <select
                  className="form-input"
                  value={newPlatform}
                  onChange={(e) => setNewPlatform(e.target.value)}
                >
                  <option value="zoom">Zoom (RTMS / Autonomous Bot)</option>
                  <option value="google_meet">Google Meet</option>
                  <option value="teams">Microsoft Teams</option>
                  <option value="in_person">Direct / Live Mic & Audio Upload</option>
                </select>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 12 }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setShowModal(false)}
                  disabled={creating}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary btn-sm" disabled={creating || !newTitle.trim()}>
                  {creating ? (
                    <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span className="spinner" />
                      <span>Creating...</span>
                    </span>
                  ) : (
                    "Launch Meeting"
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
