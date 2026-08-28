"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, authStorage, NotificationItem } from "@/lib/api";

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [isAuth, setIsAuth] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [showNotifMenu, setShowNotifMenu] = useState(false);

  useEffect(() => {
    const loggedIn = authStorage.isLoggedIn();
    setIsAuth(loggedIn);
    if (loggedIn) {
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
            <div className="brand-icon">M</div>
            <span>Meeting Assistant</span>
          </Link>
        </div>
      </header>
    );
  }

  const unreadCount = notifications.filter((n) => !n.read).length;

  return (
    <header className="navbar">
      <div className="app-container navbar-inner">
        <Link href="/" className="brand-logo">
          <div className="brand-icon">M</div>
          <span>Meeting Assistant</span>
        </Link>

        <nav className="nav-links">
          {isAuth ? (
            <>
              <Link
                href="/dashboard"
                className={`nav-link ${pathname === "/dashboard" ? "active" : ""}`}
              >
                Dashboard
              </Link>
              <Link
                href="/meetings"
                className={`nav-link ${pathname.startsWith("/meetings") ? "active" : ""}`}
              >
                Meetings
              </Link>

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
                    background: "transparent",
                    border: "none",
                    cursor: "pointer",
                  }}
                  title="Notifications"
                >
                  <span>🔔</span>
                  {unreadCount > 0 && (
                    <span
                      style={{
                        background: "var(--accent-primary)",
                        color: "#fff",
                        fontSize: 10,
                        fontWeight: 600,
                        padding: "1px 5px",
                        borderRadius: 10,
                        lineHeight: 1.2,
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
                      top: "calc(100% + 8px)",
                      width: 320,
                      background: "var(--bg-card)",
                      border: "1px solid var(--border-card)",
                      borderRadius: "var(--radius-sm)",
                      boxShadow: "var(--shadow-panel)",
                      zIndex: 100,
                      padding: 12,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        paddingBottom: 8,
                        borderBottom: "1px solid var(--border-subtle)",
                        marginBottom: 8,
                      }}
                    >
                      <span style={{ fontSize: 13, fontWeight: 600 }}>Notifications</span>
                      {unreadCount > 0 && (
                        <button
                          onClick={handleMarkAllRead}
                          style={{
                            background: "none",
                            border: "none",
                            color: "var(--accent-blue)",
                            fontSize: 11,
                            cursor: "pointer",
                          }}
                        >
                          Mark all read
                        </button>
                      )}
                    </div>

                    <div style={{ maxHeight: 280, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
                      {notifications.length === 0 ? (
                        <div style={{ textAlign: "center", padding: "20px 0", fontSize: 12, color: "var(--text-muted)" }}>
                          No notifications yet.
                        </div>
                      ) : (
                        notifications.map((n) => (
                          <div
                            key={n.id}
                            onClick={() => handleNotificationClick(n)}
                            style={{
                              padding: "8px 10px",
                              borderRadius: "var(--radius-sm)",
                              background: n.read ? "transparent" : "var(--bg-input)",
                              border: n.read ? "1px solid transparent" : "1px solid var(--border-subtle)",
                              cursor: "pointer",
                              fontSize: 12,
                            }}
                          >
                            <div style={{ fontWeight: n.read ? 400 : 600, marginBottom: 2 }}>{n.title}</div>
                            {n.body && (
                              <div style={{ color: "var(--text-muted)", fontSize: 11, lineHeight: 1.4 }}>
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

              <button
                onClick={handleLogout}
                className="btn btn-secondary btn-sm"
                style={{ padding: "6px 12px", fontSize: 13 }}
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
