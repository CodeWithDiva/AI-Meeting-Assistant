"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AdminUser, api, authStorage } from "@/lib/api";

export default function AdminTeamPage() {
  const router = useRouter();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!authStorage.isLoggedIn()) { router.push("/login"); return; }
    api.getMe().then((me) => {
      if (me.role !== "admin") { router.push("/dashboard"); return; }
      loadUsers();
    }).catch(() => router.push("/login"));
  }, [router]);

  async function loadUsers() {
    try {
      const data = await api.getAdminUsers();
      setUsers(data);
    } catch (e: any) {
      setError(e.message || "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  const filtered = users.filter(
    (u) =>
      u.email.toLowerCase().includes(search.toLowerCase()) ||
      (u.full_name || "").toLowerCase().includes(search.toLowerCase())
  );

  const admins = filtered.filter((u) => u.role === "admin");
  const employees = filtered.filter((u) => u.role !== "admin");

  function formatDate(d: string | null | undefined) {
    if (!d) return "—";
    return new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-primary)" }}>
        <div className="spinner" />
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-primary)", color: "var(--text-primary)" }}>
      {/* Header */}
      <header style={{ background: "var(--bg-glass)", borderBottom: "1px solid var(--border-subtle)", padding: "1rem 2rem", display: "flex", alignItems: "center", gap: "1rem", backdropFilter: "blur(12px)", position: "sticky", top: 0, zIndex: 50 }}>
        <Link href="/dashboard" style={{ color: "var(--text-muted)", textDecoration: "none", fontSize: "0.875rem" }}>← Dashboard</Link>
        <h1 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, background: "linear-gradient(135deg, #a855f7, #ec4899)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
          Team
        </h1>
        <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: "0.875rem" }}>{users.length} members</span>
      </header>

      <div style={{ maxWidth: "1000px", margin: "0 auto", padding: "2rem" }}>
        {error && (
          <div style={{ marginBottom: "1rem", padding: "0.75rem 1rem", background: "rgba(239,68,68,0.15)", border: "1px solid rgba(239,68,68,0.4)", borderRadius: "0.5rem", color: "#f87171", fontSize: "0.875rem" }}>
            {error}
          </div>
        )}

        {/* Stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1rem", marginBottom: "2rem" }}>
          {[
            { label: "Total Members", value: users.length, icon: "👥", color: "var(--accent-cyan)" },
            { label: "Admins", value: admins.length, icon: "🔑", color: "#a855f7" },
            { label: "Employees", value: employees.length, icon: "👤", color: "var(--accent-emerald)" },
          ].map((stat) => (
            <div key={stat.label} style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: "1rem", padding: "1.25rem", textAlign: "center" }}>
              <div style={{ fontSize: "1.75rem", marginBottom: "0.25rem" }}>{stat.icon}</div>
              <div style={{ fontSize: "2rem", fontWeight: 700, color: stat.color }}>{stat.value}</div>
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>{stat.label}</div>
            </div>
          ))}
        </div>

        {/* Search */}
        <div style={{ marginBottom: "1.5rem" }}>
          <input
            type="text"
            placeholder="Search by email or name..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: "100%", padding: "0.75rem 1rem", background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: "0.75rem", color: "var(--text-primary)", fontSize: "0.9rem", outline: "none", boxSizing: "border-box" }}
          />
        </div>

        {/* User table */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: "1rem", overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--bg-glass)", borderBottom: "1px solid var(--border-subtle)" }}>
                {["Member", "Role", "Meetings", "Tasks", "Joined"].map((h) => (
                  <th key={h} style={{ padding: "0.875rem 1rem", textAlign: "left", fontSize: "0.8rem", fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((user, i) => (
                <tr
                  key={user.id}
                  style={{ borderBottom: i < filtered.length - 1 ? "1px solid var(--border-subtle)" : "none", transition: "background 0.15s" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.03)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                >
                  <td style={{ padding: "1rem", display: "flex", alignItems: "center", gap: "0.75rem" }}>
                    <div style={{
                      width: 36, height: 36, borderRadius: "50%",
                      background: user.role === "admin" ? "linear-gradient(135deg, #a855f7, #ec4899)" : "linear-gradient(135deg, var(--accent-cyan), var(--accent-emerald))",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: "0.875rem", fontWeight: 700, color: "#fff", flexShrink: 0,
                    }}>
                      {(user.full_name || user.email).charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>{user.full_name || "—"}</div>
                      <div style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>{user.email}</div>
                    </div>
                  </td>
                  <td style={{ padding: "1rem" }}>
                    <span style={{
                      padding: "0.25rem 0.65rem", borderRadius: "9999px", fontSize: "0.75rem", fontWeight: 600,
                      background: user.role === "admin" ? "rgba(168,85,247,0.15)" : "rgba(34,211,238,0.1)",
                      color: user.role === "admin" ? "#c084fc" : "var(--accent-cyan)",
                      border: `1px solid ${user.role === "admin" ? "rgba(168,85,247,0.3)" : "rgba(34,211,238,0.2)"}`,
                    }}>
                      {user.role === "admin" ? "🔑 Admin" : "👤 Employee"}
                    </span>
                  </td>
                  <td style={{ padding: "1rem", color: "var(--accent-cyan)", fontWeight: 600 }}>{user.meeting_count}</td>
                  <td style={{ padding: "1rem", color: "var(--accent-emerald)", fontWeight: 600 }}>{user.task_count}</td>
                  <td style={{ padding: "1rem", color: "var(--text-muted)", fontSize: "0.85rem" }}>{formatDate(user.created_at)}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={5} style={{ padding: "3rem", textAlign: "center", color: "var(--text-muted)" }}>
                    No team members found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
