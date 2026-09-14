"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, authStorage, NotificationItem, WorkspaceSearchResult } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import Icon from "./Icon";
import Waveform from "./Waveform";

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [isAuth, setIsAuth] = useState(false);
  const [currentUser, setCurrentUser] = useState<{ email: string; full_name?: string | null; role?: string } | null>(null);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [showNotifMenu, setShowNotifMenu] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<WorkspaceSearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);
  const notifRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const loggedIn = authStorage.isLoggedIn();
    setIsAuth(loggedIn);
    if (loggedIn) {
      api.getMe().then(setCurrentUser).catch(() => setCurrentUser(null));
      loadNotifications();
    }
  }, [pathname]);

  useEffect(() => {
    if (!isAuth) return;
    const interval = window.setInterval(() => {
      api.getUnreadNotificationCount().then(setUnread).catch(() => undefined);
    }, 20000);
    return () => window.clearInterval(interval);
  }, [isAuth]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) setShowNotifMenu(false);
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) setShowSearch(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  useEffect(() => {
    if (!showSearch) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setShowSearch(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [showSearch]);

  useEffect(() => {
    if (!searchQuery.trim() || searchQuery.trim().length < 2) {
      setSearchResults(null);
      return;
    }
    setSearching(true);
    const handle = window.setTimeout(() => {
      api
        .searchWorkspace(searchQuery.trim())
        .then(setSearchResults)
        .catch(() => setSearchResults(null))
        .finally(() => setSearching(false));
    }, 280);
    return () => window.clearTimeout(handle);
  }, [searchQuery]);

  async function loadNotifications() {
    try {
      const [list, count] = await Promise.all([api.getNotifications(), api.getUnreadNotificationCount()]);
      setNotifications(list);
      setUnread(count);
    } catch {
      // ignore
    }
  }

  async function handleMarkAllRead() {
    try {
      await api.markAllNotificationsRead();
      setNotifications(notifications.map((n) => ({ ...n, read: true })));
      setUnread(0);
    } catch {}
  }

  async function handleNotificationClick(notif: NotificationItem) {
    if (!notif.read) {
      try {
        await api.markNotificationRead(notif.id);
        setNotifications(notifications.map((n) => (n.id === notif.id ? { ...n, read: true } : n)));
        setUnread((n) => Math.max(0, n - 1));
      } catch {}
    }
    setShowNotifMenu(false);
    if (notif.meeting_id) router.push(`/meetings/${notif.meeting_id}`);
    else router.push("/tasks");
  }

  function goToSearchResult(path: string) {
    setShowSearch(false);
    setSearchQuery("");
    router.push(path);
  }

  const handleLogout = () => {
    authStorage.clearToken();
    setIsAuth(false);
    setShowNotifMenu(false);
    router.push("/login");
  };

  if (pathname === "/login" || pathname === "/accept-invite") {
    return (
      <header className="navbar">
        <div className="app-container navbar-inner">
          <Link href="/" className="brand-logo">
            <div className="brand-icon"><Waveform size={15} active={false} /></div>
            <span>AI Meeting Assistant</span>
          </Link>
        </div>
      </header>
    );
  }

  const isAdmin = currentUser?.role === "admin";
  const hasResults = searchResults && (searchResults.meetings.length || searchResults.transcript.length || searchResults.decisions.length || searchResults.tasks.length);

  return (
    <header className="navbar">
      <div className="app-container navbar-inner">
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <Link href={isAuth ? (isAdmin ? "/admin" : "/dashboard") : "/"} className="brand-logo">
            <div className="brand-icon"><Waveform size={15} active={false} /></div>
            <span style={{ fontSize: 15 }}>AI Meeting Assistant</span>
          </Link>
        </div>

        {isAuth ? (
          <>
            <nav className="nav-links" style={{ flex: 1, justifyContent: "center" }}>
              {isAdmin ? (
                <>
                  <Link href="/admin" className={`nav-link ${pathname === "/admin" ? "active" : ""}`}>
                    <Icon name="briefcase" size={15} /><span>Admin</span>
                  </Link>
                  <Link href="/meetings" className={`nav-link ${pathname.startsWith("/meetings") ? "active" : ""}`}>
                    <Icon name="video" size={15} /><span>Meetings</span>
                  </Link>
                  <Link href="/tasks" className={`nav-link ${pathname === "/tasks" ? "active" : ""}`}>
                    <Icon name="checkSquare" size={15} /><span>Tasks</span>
                  </Link>
                  <Link href="/admin/team" className={`nav-link ${pathname === "/admin/team" ? "active" : ""}`}>
                    <Icon name="users" size={15} /><span>Team</span>
                  </Link>
                  <Link href="/admin/analytics" className={`nav-link ${pathname === "/admin/analytics" ? "active" : ""}`}>
                    <Icon name="chart" size={15} /><span>Analytics</span>
                  </Link>
                </>
              ) : (
                <>
                  <Link href="/dashboard" className={`nav-link ${pathname === "/dashboard" ? "active" : ""}`}>
                    <Icon name="home" size={15} /><span>Dashboard</span>
                  </Link>
                  <Link href="/meetings" className={`nav-link ${pathname.startsWith("/meetings") ? "active" : ""}`}>
                    <Icon name="video" size={15} /><span>Meetings</span>
                  </Link>
                  <Link href="/tasks" className={`nav-link ${pathname === "/tasks" ? "active" : ""}`}>
                    <Icon name="checkSquare" size={15} /><span>Tasks</span>
                  </Link>
                </>
              )}
            </nav>

            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div ref={searchRef} style={{ position: "relative" }}>
                <button type="button" className="icon-btn" onClick={() => setShowSearch((v) => !v)} title="Search everything">
                  <Icon name="search" size={16} />
                </button>
                {showSearch && (
                  <div
                    style={{
                      position: "absolute", right: 0, top: "calc(100% + 8px)", width: 380,
                      background: "var(--bg-surface)", border: "1px solid var(--border-card)",
                      borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-lg)", zIndex: 100,
                      padding: 10,
                    }}
                  >
                    <div style={{ position: "relative", marginBottom: hasResults || searching ? 8 : 0 }}>
                      <Icon name="search" size={14} className="mono" />
                      <input
                        autoFocus
                        type="text"
                        className="form-input"
                        style={{ paddingLeft: 34 }}
                        placeholder="Search meetings, transcripts, tasks…"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                      />
                      <span style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--text-dim)" }}>
                        <Icon name="search" size={14} />
                      </span>
                    </div>
                    {searching && <div style={{ padding: "8px 4px", fontSize: 12.5, color: "var(--text-muted)" }}>Searching…</div>}
                    {!searching && searchQuery.trim().length >= 2 && !hasResults && (
                      <div style={{ padding: "8px 4px", fontSize: 12.5, color: "var(--text-muted)" }}>No matches.</div>
                    )}
                    {!searching && hasResults && (
                      <div style={{ maxHeight: 360, overflowY: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
                        {searchResults!.meetings.length > 0 && (
                          <div>
                            <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.05em", padding: "2px 6px" }}>Meetings</div>
                            {searchResults!.meetings.map((m) => (
                              <button key={m.id} onClick={() => goToSearchResult(`/meetings/${m.id}`)} className="search-result-row">
                                <Icon name="video" size={13} />
                                <span>{m.title}</span>
                              </button>
                            ))}
                          </div>
                        )}
                        {searchResults!.decisions.length > 0 && (
                          <div>
                            <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.05em", padding: "2px 6px" }}>Decisions</div>
                            {searchResults!.decisions.map((d, i) => (
                              <button key={i} onClick={() => goToSearchResult(`/meetings/${d.meeting_id}`)} className="search-result-row">
                                <Icon name="flag" size={13} />
                                <span>{d.text}</span>
                              </button>
                            ))}
                          </div>
                        )}
                        {searchResults!.tasks.length > 0 && (
                          <div>
                            <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.05em", padding: "2px 6px" }}>Tasks</div>
                            {searchResults!.tasks.map((t) => (
                              <button key={t.id} onClick={() => goToSearchResult(`/meetings/${t.meeting_id}`)} className="search-result-row">
                                <Icon name="checkSquare" size={13} />
                                <span>{t.task}</span>
                              </button>
                            ))}
                          </div>
                        )}
                        {searchResults!.transcript.length > 0 && (
                          <div>
                            <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.05em", padding: "2px 6px" }}>Transcript</div>
                            {searchResults!.transcript.map((s, i) => (
                              <button key={i} onClick={() => goToSearchResult(`/meetings/${s.meeting_id}`)} className="search-result-row">
                                <Icon name="message" size={13} />
                                <span>{s.text}</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div ref={notifRef} style={{ position: "relative" }}>
                <button type="button" onClick={() => setShowNotifMenu((v) => !v)} className="icon-btn" title="Notifications">
                  <Icon name="bell" size={16} />
                  {unread > 0 && (
                    <span
                      style={{
                        position: "absolute", top: -4, right: -4,
                        background: "var(--accent-rose)", color: "var(--text-on-accent)",
                        fontSize: 10, fontWeight: 700, minWidth: 16, height: 16, borderRadius: 999,
                        display: "flex", alignItems: "center", justifyContent: "center", padding: "0 3px",
                        border: "2px solid var(--bg-surface)",
                      }}
                    >
                      {unread > 9 ? "9+" : unread}
                    </span>
                  )}
                </button>

                {showNotifMenu && (
                  <div
                    style={{
                      position: "absolute", right: 0, top: "calc(100% + 8px)", width: 340,
                      background: "var(--bg-surface)", border: "1px solid var(--border-card)",
                      borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-lg)", zIndex: 100, padding: 14,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: 10, borderBottom: "1px solid var(--border-subtle)", marginBottom: 10 }}>
                      <span style={{ fontSize: 13, fontWeight: 700 }}>Notifications</span>
                      {unread > 0 && (
                        <button onClick={handleMarkAllRead} style={{ background: "none", border: "none", color: "var(--accent-primary)", fontSize: 11.5, fontWeight: 600, cursor: "pointer" }}>
                          Mark all read
                        </button>
                      )}
                    </div>
                    <div style={{ maxHeight: 320, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
                      {notifications.length === 0 ? (
                        <div style={{ textAlign: "center", padding: "28px 0", fontSize: 13, color: "var(--text-muted)" }}>
                          You&apos;re all caught up.
                        </div>
                      ) : (
                        notifications.map((n) => (
                          <div
                            key={n.id}
                            onClick={() => handleNotificationClick(n)}
                            style={{
                              padding: "9px 10px", borderRadius: "var(--radius-sm)", cursor: "pointer",
                              background: n.read ? "transparent" : "var(--accent-primary-tint)",
                            }}
                          >
                            <div style={{ fontWeight: n.read ? 500 : 700, fontSize: 12.5, marginBottom: 2 }}>{n.title}</div>
                            {n.body && <div style={{ color: "var(--text-muted)", fontSize: 12, lineHeight: 1.4 }}>{n.body}</div>}
                            {n.created_at && <div style={{ color: "var(--text-dim)", fontSize: 10.5, marginTop: 3 }}>{relativeTime(n.created_at)}</div>}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}
              </div>

              <button type="button" onClick={handleLogout} className="btn btn-secondary btn-sm" title="Sign out">
                <span
                  className="avatar"
                  style={{ width: 22, height: 22, fontSize: 10 }}
                >
                  {(currentUser?.full_name || currentUser?.email || "?").charAt(0).toUpperCase()}
                </span>
                <span style={{ maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {currentUser?.full_name || currentUser?.email?.split("@")[0] || "Account"}
                </span>
              </button>
            </div>
          </>
        ) : (
          <Link href="/login" className="btn btn-primary btn-sm">Sign in</Link>
        )}
      </div>

      <style>{`
        .search-result-row {
          display: flex; align-items: center; gap: 8px; width: 100%;
          text-align: left; background: none; border: none; cursor: pointer;
          padding: 7px 8px; border-radius: var(--radius-xs); font-size: 12.5px;
          color: var(--text-secondary);
        }
        .search-result-row:hover { background: var(--bg-subtle); color: var(--text-primary); }
        .search-result-row span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      `}</style>
    </header>
  );
}
