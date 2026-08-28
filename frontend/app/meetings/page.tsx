"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api, authStorage, Meeting } from "@/lib/api";

export default function MeetingsListPage() {
  const router = useRouter();
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [search, setSearch] = useState("");
  const [filterPlatform, setFilterPlatform] = useState("all");
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
    loadMeetings();
  }, [router]);

  async function loadMeetings() {
    setLoading(true);
    setError("");
    try {
      const data = await api.getMeetings();
      setMeetings(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load meetings");
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

  async function handleDeleteMeeting(e: React.MouseEvent, id: number) {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm("Are you sure you want to delete this meeting?")) {
      return;
    }

    try {
      await api.deleteMeeting(id);
      setMeetings(meetings.filter((m) => m.id !== id));
    } catch (err: any) {
      setError(err?.message || "Failed to delete meeting");
    }
  }

  const filteredMeetings = meetings.filter((m) => {
    const matchesSearch = m.title.toLowerCase().includes(search.toLowerCase());
    const matchesPlatform =
      filterPlatform === "all" ||
      (m.platform && m.platform.toLowerCase() === filterPlatform.toLowerCase());
    return matchesSearch && matchesPlatform;
  });

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
          marginBottom: 24,
        }}
      >
        <div>
          <h1 style={{ fontSize: 22, marginBottom: 4 }}>Meetings</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
            Manage meeting sessions, recordings, and analysis notes.
          </p>
        </div>

        <button onClick={() => setShowModal(true)} className="btn btn-primary btn-sm">
          + New Meeting
        </button>
      </div>

      {error && <div className="alert-box alert-error">{error}</div>}

      {/* Search & Filter */}
      <div
        style={{
          display: "flex",
          gap: 12,
          marginBottom: 20,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <div style={{ flex: 1, minWidth: 240 }}>
          <input
            type="text"
            className="form-input"
            placeholder="Search meetings..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div style={{ width: 160 }}>
          <select
            className="form-input"
            value={filterPlatform}
            onChange={(e) => setFilterPlatform(e.target.value)}
          >
            <option value="all">All Platforms</option>
            <option value="zoom">Zoom</option>
            <option value="google_meet">Google Meet</option>
            <option value="teams">Microsoft Teams</option>
            <option value="in_person">Direct / Audio</option>
          </select>
        </div>
      </div>

      {/* List */}
      {loading ? (
        <div style={{ textAlign: "center", padding: "80px 0" }}>
          <div className="spinner" style={{ margin: "0 auto 16px" }}></div>
          <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>Loading meetings...</p>
        </div>
      ) : filteredMeetings.length === 0 ? (
        <div className="glass-panel" style={{ textAlign: "center", padding: "50px 20px" }}>
          <p style={{ color: "var(--text-secondary)", fontSize: 14, marginBottom: 16 }}>
            {search || filterPlatform !== "all"
              ? "No meetings matched your search criteria."
              : "No meetings recorded yet."}
          </p>
          <button onClick={() => setShowModal(true)} className="btn btn-primary btn-sm">
            Create Meeting
          </button>
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
            gap: 16,
          }}
        >
          {filteredMeetings.map((m) => (
            <Link
              key={m.id}
              href={`/meetings/${m.id}`}
              className="glass-panel glass-panel-hover"
              style={{
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                height: "100%",
                padding: 18,
              }}
            >
              <div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: 10,
                  }}
                >
                  <span className="badge badge-indigo">
                    {m.platform || "Direct"}
                  </span>
                  <button
                    onClick={(e) => handleDeleteMeeting(e, m.id)}
                    className="btn btn-secondary btn-sm"
                    title="Delete meeting"
                    style={{ padding: "2px 6px", fontSize: 11 }}
                  >
                    Delete
                  </button>
                </div>

                <h3 style={{ fontSize: 15, marginBottom: 6, lineHeight: 1.3 }}>{m.title}</h3>

                <p
                  style={{
                    fontSize: 13,
                    color: "var(--text-secondary)",
                    lineHeight: 1.5,
                    marginBottom: 14,
                    display: "-webkit-box",
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical",
                    overflow: "hidden",
                  }}
                >
                  {m.transcript
                    ? m.transcript
                    : "No transcript yet. Upload audio to generate notes."}
                </p>
              </div>

              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  paddingTop: 12,
                  borderTop: "1px solid var(--border-subtle)",
                  fontSize: 12,
                  color: "var(--text-muted)",
                }}
              >
                <span>{m.created_at ? new Date(m.created_at).toLocaleDateString() : "Recent"}</span>
                <div>
                  {m.transcript ? (
                    <span className="badge badge-emerald">Ready</span>
                  ) : (
                    <span className="badge badge-amber">Awaiting Audio</span>
                  )}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

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
                  <option value="in_person">Direct / Audio</option>
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
