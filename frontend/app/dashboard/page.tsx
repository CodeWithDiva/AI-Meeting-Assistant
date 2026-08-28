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
      const [statsData, meetingsData, tasksData] = await Promise.all([
        api.getDashboardStats().catch(() => ({
          total_meetings: 0,
          total_tasks: 0,
          pending_tasks: 0,
          done_tasks: 0,
          recent_meetings: 0,
        })),
        api.getMeetings().catch(() => []),
        api.getAllTasks("pending").catch(() => []),
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

  async function handleToggleTask(taskId: number, currentStatus: string) {
    const nextStatus = currentStatus === "done" ? "pending" : "done";
    try {
      await api.updateTask(taskId, { status: nextStatus });
      const [updatedTasks, updatedStats] = await Promise.all([
        api.getAllTasks("pending"),
        api.getDashboardStats(),
      ]);
      setTasks(updatedTasks);
      setStats(updatedStats);
    } catch (err: any) {
      setError(err?.message || "Failed to update task status");
    }
  }

  if (loading) {
    return (
      <div className="app-container" style={{ textAlign: "center", padding: "100px 0" }}>
        <div className="spinner" style={{ margin: "0 auto 16px" }}></div>
        <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>Loading workspace...</p>
      </div>
    );
  }

  return (
    <div className="app-container">
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 16,
          marginBottom: 28,
        }}
      >
        <div>
          <h1 style={{ fontSize: 22, marginBottom: 4 }}>Dashboard</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
            Overview of meeting transcripts, notes, and pending action items.
          </p>
        </div>

        <button onClick={() => setShowModal(true)} className="btn btn-primary btn-sm">
          + New Meeting
        </button>
      </div>

      {error && <div className="alert-box alert-error">{error}</div>}

      {/* Stats Cards */}
      <div className="stats-grid">
        <div className="stat-card">
          <span className="stat-label">Total Meetings</span>
          <span className="stat-value">{stats?.total_meetings ?? meetings.length}</span>
        </div>

        <div className="stat-card">
          <span className="stat-label">Pending Tasks</span>
          <span className="stat-value">{stats?.pending_tasks ?? tasks.length}</span>
        </div>

        <div className="stat-card">
          <span className="stat-label">Completed Tasks</span>
          <span className="stat-value">{stats?.done_tasks ?? 0}</span>
        </div>

        <div className="stat-card">
          <span className="stat-label">Processed Tasks</span>
          <span className="stat-value">{stats?.total_tasks ?? 0}</span>
        </div>
      </div>

      {/* Main Content Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))", gap: 20 }}>
        {/* Recent Meetings */}
        <div className="glass-panel">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 16,
            }}
          >
            <h2 style={{ fontSize: 16 }}>Recent Meetings</h2>
            <Link href="/meetings" style={{ fontSize: 13, color: "var(--accent-blue)" }}>
              View all ({meetings.length})
            </Link>
          </div>

          {meetings.length === 0 ? (
            <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)", fontSize: 14 }}>
              <p style={{ marginBottom: 12 }}>No meetings recorded yet.</p>
              <button onClick={() => setShowModal(true)} className="btn btn-secondary btn-sm">
                Create First Meeting
              </button>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {meetings.slice(0, 5).map((m) => (
                <Link
                  key={m.id}
                  href={`/meetings/${m.id}`}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "12px 14px",
                    borderRadius: "var(--radius-sm)",
                    background: "var(--bg-input)",
                    border: "1px solid var(--border-subtle)",
                  }}
                  className="glass-panel-hover"
                >
                  <div>
                    <h4 style={{ fontSize: 14, marginBottom: 2 }}>{m.title}</h4>
                    <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                      {m.platform || "Direct"} · {m.created_at ? new Date(m.created_at).toLocaleDateString() : "Recent"}
                    </span>
                  </div>

                  <div>
                    {m.transcript ? (
                      <span className="badge badge-emerald">Ready</span>
                    ) : (
                      <span className="badge badge-amber">Awaiting Audio</span>
                    )}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Action Items */}
        <div className="glass-panel">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 16,
            }}
          >
            <h2 style={{ fontSize: 16 }}>Pending Action Items</h2>
            <span className="badge badge-indigo">{tasks.length}</span>
          </div>

          {tasks.length === 0 ? (
            <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)", fontSize: 14 }}>
              <p>No pending action items.</p>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {tasks.slice(0, 6).map((t) => (
                <div
                  key={t.id}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 10,
                    padding: "12px 14px",
                    borderRadius: "var(--radius-sm)",
                    background: "var(--bg-input)",
                    border: "1px solid var(--border-subtle)",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={t.status === "done"}
                    onChange={() => handleToggleTask(t.id, t.status)}
                    style={{
                      marginTop: 3,
                      cursor: "pointer",
                      width: 15,
                      height: 15,
                    }}
                  />
                  <div style={{ flex: 1 }}>
                    <p style={{ fontSize: 13, marginBottom: 2, lineHeight: 1.4 }}>
                      {t.task}
                    </p>
                    <div style={{ display: "flex", gap: 8, fontSize: 11, color: "var(--text-muted)" }}>
                      {t.assignee && <span>Assignee: {t.assignee}</span>}
                      {t.deadline && <span>Due: {t.deadline}</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Modal */}
      {showModal && (
        <div className="modal-backdrop" onClick={() => setShowModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ fontSize: 18, marginBottom: 6 }}>Create New Meeting</h3>
            <p style={{ color: "var(--text-secondary)", fontSize: 13, marginBottom: 18 }}>
              Enter meeting details to begin session.
            </p>

            <form onSubmit={handleCreateMeeting}>
              <div className="form-group">
                <label className="form-label">Meeting Title</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="e.g. Q3 Sprint Planning"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  autoFocus
                  required
                />
              </div>

              <div className="form-group" style={{ marginBottom: 20 }}>
                <label className="form-label">Platform</label>
                <select
                  className="form-input"
                  value={newPlatform}
                  onChange={(e) => setNewPlatform(e.target.value)}
                >
                  <option value="zoom">Zoom</option>
                  <option value="google_meet">Google Meet</option>
                  <option value="teams">Microsoft Teams</option>
                  <option value="in_person">Direct / Audio File</option>
                </select>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setShowModal(false)}
                  disabled={creating}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary btn-sm" disabled={creating || !newTitle.trim()}>
                  {creating ? "Creating..." : "Create Meeting"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
