"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, authStorage, NotificationItem } from "@/lib/api";

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [isAuth, setIsAuth] = useState(false);
  const [currentUser, setCurrentUser] = useState<{ email: string; full_name?: string | null; role?: string } | null>(null);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [showNotifMenu, setShowNotifMenu] = useState(false);

  useEffect(() => {
    const loggedIn = authStorage.isLoggedIn();
    setIsAuth(loggedIn);
    if (loggedIn) {
      api.getMe().then(setCurrentUser).catch(() => setCurrentUser(null));
      loadNotifications();
    }
  }, [pathname]);

  async function loadNotifications() {
    try {
      const list = await api.getNotifications();
      setNotifications(list);
    } catch {
      // ignore
    }
  }

  async function handleMarkAllRead() {
    try {
      await api.markAllNotificationsRead();
      setNotifications(notifications.map((n) => ({ ...n, read: true })));
    } catch {}
  }

  async function handleNotificationClick(notif: NotificationItem) {
    if (!notif.read) {
      try {
        await api.markNotificationRead(notif.id);
        setNotifications(
          notifications.map((n) => (n.id === notif.id ? { ...n, read: true } : n))
        );
      } catch {}
    }
    setShowNotifMenu(false);
    if (notif.meeting_id) {
      router.push(`/meetings/${notif.meeting_id}`);
    }
  }

  const handleLogout = () => {
    authStorage.clearToken();
    setIsAuth(false);
    setShowNotifMenu(false);
    router.push("/login");
  };

  if (pathname === "/login") {
    return (
      <header className="navbar">
        <div className="app-container navbar-inner">
          <Link href="/" className="brand-logo">
            <div className="brand-icon" aria-hidden="true" />
            <span>AI Meeting Assistant</span>
          </Link>
        </div>
      </header>
    );
  }

  const unreadCount = notifications.filter((n) => !n.read).length;

  return (
    <header className="navbar">
      <div className="app-container navbar-inner">
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <Link href="/" className="brand-logo">
              <div className="brand-icon" aria-hidden="true" />
            <div style={{ display: "flex", flexDirection: "column" }}>
              <span style={{ fontSize: 16, fontWeight: 800, letterSpacing: "-0.02em" }}>AI Meeting Assistant</span>
              <span style={{ fontSize: 10, color: "var(--accent-indigo)", fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                Meeting intelligence
              </span>
            </div>
          </Link>

          {isAuth && (
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "3px 10px",
                borderRadius: "var(--radius-full)",
                background: "rgba(16, 185, 129, 0.08)",
                border: "1px solid rgba(16, 185, 129, 0.25)",
                fontSize: 11,
                color: "#6ee7b7",
                fontWeight: 500,
              }}
            >
              <span className="status-dot status-dot-active" />
              <span>Whisper & LLM Online</span>
            </div>
          )}
        </div>

        <nav className="nav-links">
          {isAuth ? (
            <>
              <Link
                href="/dashboard"
                className={`nav-link ${pathname === "/dashboard" ? "active" : ""}`}
              >
                <span aria-hidden="true">01</span>
                <span>Dashboard</span>
              </Link>
              <Link
                href="/meetings"
                className={`nav-link ${pathname.startsWith("/meetings") ? "active" : ""}`}
              >
                <span aria-hidden="true">02</span>
                <span>Meetings</span>
              </Link>
              {currentUser?.role === "admin" && (
                <>
                  <Link href="/dashboard#tasks" className={`nav-link ${pathname === "/dashboard" ? "active" : ""}`}>
                    <span aria-hidden="true">03</span>
                    <span>Tasks</span>
                  </Link>
                  <span className="nav-link" style={{ cursor: "default", color: "var(--text-muted)" }}>Team</span>
                  <span className="nav-link" style={{ cursor: "default", color: "var(--text-muted)" }}>Settings</span>
                </>
              )}

              {/* Notifications Dropdown */}
              <div style={{ position: "relative" }}>
                <button
                  type="button"
                  onClick={() => setShowNotifMenu(!showNotifMenu)}
                  className="nav-link"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    position: "relative",
                    background: "rgba(255, 255, 255, 0.04)",
                    border: "1px solid var(--border-subtle)",
                    cursor: "pointer",
                    padding: "7px 12px",
                  }}
                  title="Notifications"
                >
                  <span style={{ fontSize: 14 }}>🔔</span>
                  {unreadCount > 0 && (
                    <span
                      style={{
                        background: "var(--accent-rose)",
                        color: "#fff",
                        fontSize: 10,
                        fontWeight: 700,
                        padding: "1px 6px",
                        borderRadius: "10px",
                        lineHeight: 1.2,
                        boxShadow: "0 0 10px rgba(244, 63, 94, 0.6)",
                      }}
                    >
                      {unreadCount}
                    </span>
                  )}
                </button>

                {showNotifMenu && (
                  <div
                    style={{
                      position: "absolute",
                      right: 0,
                      top: "calc(100% + 10px)",
                      width: 340,
                      background: "var(--bg-surface)",
                      border: "1px solid var(--border-card)",
                      borderRadius: "var(--radius-md)",
                      boxShadow: "var(--shadow-lg), 0 0 30px rgba(0,0,0,0.6)",
                      zIndex: 100,
                      padding: 16,
                      animation: "scaleUp 0.15s ease",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        paddingBottom: 10,
                        borderBottom: "1px solid var(--border-subtle)",
                        marginBottom: 10,
                      }}
                    >
                      <span style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
                        Notifications ({notifications.length})
                      </span>
                      {unreadCount > 0 && (
                        <button
                          onClick={handleMarkAllRead}
                          style={{
                            background: "none",
                            border: "none",
                            color: "var(--accent-indigo)",
                            fontSize: 11,
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          Mark all read
                        </button>
                      )}
                    </div>

                    <div style={{ maxHeight: 300, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
                      {notifications.length === 0 ? (
                        <div style={{ textAlign: "center", padding: "28px 0", fontSize: 13, color: "var(--text-muted)" }}>
                          No notifications yet.
                        </div>
                      ) : (
                        notifications.map((n) => (
                          <div
                            key={n.id}
                            onClick={() => handleNotificationClick(n)}
                            style={{
                              padding: "10px 12px",
                              borderRadius: "var(--radius-sm)",
                              background: n.read ? "transparent" : "rgba(99, 102, 241, 0.08)",
                              border: n.read ? "1px solid rgba(255, 255, 255, 0.04)" : "1px solid rgba(99, 102, 241, 0.25)",
                              cursor: "pointer",
                              transition: "all 0.15s ease",
                            }}
                          >
                            <div style={{ fontWeight: n.read ? 500 : 700, fontSize: 13, marginBottom: 2, color: n.read ? "var(--text-secondary)" : "#ffffff" }}>
                              {n.title}
                            </div>
                            {n.body && (
                              <div style={{ color: "var(--text-muted)", fontSize: 12, lineHeight: 1.4 }}>
                                {n.body}
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}
              </div>
              <button type="button" className="nav-link" onClick={handleLogout} title="Sign out">
                {currentUser?.full_name || currentUser?.email?.split("@")[0] || "Profile"} · Sign out
              </button>

              <button
                onClick={handleLogout}
                className="btn btn-secondary btn-sm"
                style={{ padding: "7px 14px" }}
              >
                Sign out
              </button>
            </>
          ) : (
            <Link href="/login" className="btn btn-primary btn-sm">
              Sign In
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}
