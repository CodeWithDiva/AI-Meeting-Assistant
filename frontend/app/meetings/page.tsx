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

  function getPlatformBadge(platform?: string | null) {
    const p = (platform || "direct").toLowerCase();
    if (p.includes("zoom")) return <span className="badge badge-cyan">📹 Zoom</span>;
    if (p.includes("meet")) return <span className="badge badge-emerald">🟢 Google Meet</span>;
    if (p.includes("team")) return <span className="badge badge-purple">🟣 MS Teams</span>;
    return <span className="badge badge-indigo">🎙️ Direct Audio</span>;
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
          <h1 style={{ fontSize: 24, marginBottom: 4 }}>Meeting Workspaces</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>
            Explore recorded sessions, audio transcripts, and AI-extracted notes.
          </p>
        </div>

        <button onClick={() => setShowModal(true)} className="btn btn-primary">
          <span>+</span>
          <span>New Meeting</span>
        </button>
      </div>

      {error && <div className="alert-box alert-error">{error}</div>}

      {/* Search & Filter Toolbar */}
      <div
        className="glass-panel"
        style={{
          display: "flex",
          gap: 14,
          marginBottom: 24,
          flexWrap: "wrap",
          alignItems: "center",
          padding: "16px 20px",
        }}
      >
        <div style={{ flex: 1, minWidth: 260 }}>
          <input
            type="text"
            className="form-input"
            placeholder="Search meetings by title or keywords..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {["all", "zoom", "google_meet", "teams", "in_person"].map((p) => {
            const label =
              p === "all"
                ? "All"
                : p === "zoom"
                ? "Zoom"
                : p === "google_meet"
                ? "Google Meet"
                : p === "teams"
                ? "Teams"
                : "Direct";
            const isActive = filterPlatform === p;
            return (
              <button
                key={p}
                type="button"
                onClick={() => setFilterPlatform(p)}
                className={`btn btn-sm ${isActive ? "btn-primary" : "btn-secondary"}`}
                style={{ fontSize: 12, padding: "5px 12px" }}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Grid List */}
      {loading ? (
        <div style={{ textAlign: "center", padding: "100px 0" }}>
          <div className="spinner" style={{ margin: "0 auto 16px", width: 28, height: 28, borderWidth: 3 }}></div>
          <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>Loading meeting archives...</p>
        </div>
      ) : filteredMeetings.length === 0 ? (
        <div className="glass-panel" style={{ textAlign: "center", padding: "60px 20px" }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🎙️</div>
          <h3 style={{ fontSize: 18, marginBottom: 6 }}>No meetings found</h3>
          <p style={{ color: "var(--text-secondary)", fontSize: 14, marginBottom: 20 }}>
            {search || filterPlatform !== "all"
              ? "No meetings matched your search criteria."
              : "You have not recorded any meetings yet."}
          </p>
          <button onClick={() => setShowModal(true)} className="btn btn-primary">
            Create Meeting
          </button>
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
            gap: 20,
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
                padding: 22,
                position: "relative",
              }}
            >
              <div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 12,
                  }}
                >
                  {getPlatformBadge(m.platform)}
                  <button
                    onClick={(e) => handleDeleteMeeting(e, m.id)}
                    className="btn btn-secondary btn-sm"
                    title="Delete meeting"
                    style={{ padding: "3px 8px", fontSize: 11, color: "var(--accent-rose)" }}
                  >
                    Delete
                  </button>
                </div>

                <h3 style={{ fontSize: 17, marginBottom: 8, lineHeight: 1.3, color: "#ffffff" }}>
                  {m.title}
                </h3>

                <p
                  style={{
                    fontSize: 13,
                    color: "var(--text-secondary)",
                    lineHeight: 1.5,
                    marginBottom: 16,
                    display: "-webkit-box",
                    WebkitLineClamp: 3,
                    WebkitBoxOrient: "vertical",
                    overflow: "hidden",
                  }}
                >
                  {m.transcript
                    ? m.transcript
                    : "No audio transcript generated yet. Upload an audio recording or start live microphone stream."}
                </p>
              </div>

              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  paddingTop: 14,
                  borderTop: "1px solid var(--border-subtle)",
                  fontSize: 12,
                  color: "var(--text-muted)",
                }}
              >
                <span>
                  {m.created_at
                    ? new Date(m.created_at).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })
                    : "Recent"}
                </span>

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
              Initialize a workspace session for transcription, notes, and task tracking.
            </p>

            <form onSubmit={handleCreateMeeting}>
              <div className="form-group">
                <label className="form-label">Meeting Title</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="e.g. Weekly Product Sync"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  autoFocus
                  required
                />
              </div>

              <div className="form-group" style={{ marginBottom: 24 }}>
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
                  {creating ? "Launching..." : "Launch Meeting"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
