"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api, authStorage, Meeting } from "@/lib/api";
import { formatDate, platformLabel } from "@/lib/format";
import Icon from "@/app/components/Icon";

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
      setMeetings(await api.getMeetings());
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
    if (!confirm("Delete this meeting? This cannot be undone.")) return;
    try {
      await api.deleteMeeting(id);
      setMeetings(meetings.filter((m) => m.id !== id));
    } catch (err: any) {
      setError(err?.message || "Failed to delete meeting");
    }
  }

  function platformBadge(platform?: string | null) {
    const p = (platform || "").toLowerCase();
    if (p.includes("zoom")) return <span className="badge badge-cyan"><Icon name="video" size={11} /> Zoom</span>;
    if (p.includes("meet")) return <span className="badge badge-emerald"><Icon name="video" size={11} /> Google Meet</span>;
    if (p === "attach") return <span className="badge badge-indigo"><Icon name="mic" size={11} /> Your device</span>;
    return <span className="badge badge-neutral"><Icon name="mic" size={11} /> Direct audio</span>;
  }

  const filteredMeetings = meetings.filter((m) => {
    const matchesSearch = m.title.toLowerCase().includes(search.toLowerCase());
    const matchesPlatform = filterPlatform === "all" || (m.platform && m.platform.toLowerCase() === filterPlatform.toLowerCase());
    return matchesSearch && matchesPlatform;
  });

  const filters = [
    { key: "all", label: "All" },
    { key: "zoom", label: "Zoom" },
    { key: "google_meet", label: "Google Meet" },
    { key: "attach", label: "Your device" },
  ];

  return (
    <div className="app-container">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 14, marginBottom: 22 }}>
        <div>
          <h1 style={{ fontSize: 22, marginBottom: 4 }}>Meetings</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13.5 }}>Every recorded session, its transcript, and its notes.</p>
        </div>
        <button onClick={() => setShowModal(true)} className="btn btn-primary"><Icon name="plus" size={15} /> New meeting</button>
      </div>

      {error && <div className="alert-box alert-error"><Icon name="alert" size={16} />{error}</div>}

      <div className="glass-panel" style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap", alignItems: "center", padding: "14px 16px" }}>
        <div style={{ flex: 1, minWidth: 220, position: "relative" }}>
          <input type="text" className="form-input" style={{ paddingLeft: 34 }} placeholder="Search by title…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <span style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--text-dim)" }}><Icon name="search" size={14} /></span>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {filters.map((f) => (
            <button key={f.key} type="button" onClick={() => setFilterPlatform(f.key)} className={`btn btn-sm ${filterPlatform === f.key ? "btn-primary" : "btn-secondary"}`}>
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: "100px 0" }}>
          <div className="spinner" style={{ margin: "0 auto 16px", width: 22, height: 22, borderTopColor: "var(--accent-primary)", borderColor: "var(--border-card)" }} />
          <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>Loading meetings…</p>
        </div>
      ) : filteredMeetings.length === 0 ? (
        <div className="glass-panel empty-state">
          <div className="icon-wrap"><Icon name="video" size={22} /></div>
          <h4>No meetings found</h4>
          <p>{search || filterPlatform !== "all" ? "Nothing matches your filters." : "You haven't recorded any meetings yet."}</p>
          <button onClick={() => setShowModal(true)} className="btn btn-primary btn-sm">Create a meeting</button>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 16 }}>
          {filteredMeetings.map((m) => (
            <Link key={m.id} href={`/meetings/${m.id}`} className="glass-panel glass-panel-hover" style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", padding: 20 }}>
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  {platformBadge(m.platform)}
                  <button onClick={(e) => handleDeleteMeeting(e, m.id)} className="icon-btn" style={{ width: 28, height: 28 }} title="Delete meeting">
                    <Icon name="trash" size={13} />
                  </button>
                </div>
                <h3 style={{ fontSize: 15.5, marginBottom: 8, lineHeight: 1.35 }}>{m.title}</h3>
                <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.5, marginBottom: 14, display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                  {m.transcript || "No transcript yet — upload audio, or send the assistant in."}
                </p>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 12, borderTop: "1px solid var(--border-subtle)", fontSize: 11.5, color: "var(--text-muted)" }}>
                <span>{formatDate(m.created_at, true)}</span>
                {m.transcript ? <span className="badge badge-emerald">Transcribed</span> : <span className="badge badge-amber">Awaiting audio</span>}
              </div>
            </Link>
          ))}
        </div>
      )}

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
                <input type="text" className="form-input" placeholder="e.g. Weekly product sync" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} autoFocus required />
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
