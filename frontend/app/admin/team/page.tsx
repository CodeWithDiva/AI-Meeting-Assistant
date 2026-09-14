"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AdminUser, api, authStorage } from "@/lib/api";
import { formatDate, initials } from "@/lib/format";
import Icon from "@/app/components/Icon";
import InviteEmployeeModal from "@/app/components/InviteEmployeeModal";

export default function AdminTeamPage() {
  const router = useRouter();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [currentUserId, setCurrentUserId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [search, setSearch] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    if (!authStorage.isLoggedIn()) { router.push("/login"); return; }
    api.getMe().then((me) => {
      if (me.role !== "admin") { router.push("/dashboard"); return; }
      setCurrentUserId(me.id);
      loadUsers();
    }).catch(() => router.push("/login"));
  }, [router]);

  async function loadUsers() {
    try {
      setUsers(await api.getAdminUsers());
    } catch (e: any) {
      setError(e.message || "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  async function toggleRole(user: AdminUser) {
    const nextRole = user.role === "admin" ? "employee" : "admin";
    try {
      await api.adminUpdateUser(user.id, { role: nextRole });
      await loadUsers();
    } catch (e: any) {
      setError(e.message || "Could not change that person's role.");
    }
  }

  async function resendInvite(user: AdminUser) {
    setBusyId(user.id);
    setError("");
    try {
      const result = await api.adminResendInvite(user.id);
      if (result.email_sent) {
        setSuccess(`Invite re-sent to ${user.email}.`);
      } else {
        await navigator.clipboard.writeText(result.invite_link).catch(() => undefined);
        setSuccess(`Email isn't configured — the new setup link was copied to your clipboard for ${user.email}.`);
      }
    } catch (e: any) {
      setError(e.message || "Could not resend that invite.");
    } finally {
      setBusyId(null);
    }
  }

  async function removeUser(user: AdminUser) {
    if (!confirm(`Remove ${user.full_name || user.email} from the workspace?`)) return;
    setBusyId(user.id);
    try {
      await api.adminDeleteUser(user.id);
      await loadUsers();
    } catch (e: any) {
      setError(e.message || "Could not remove that person.");
    } finally {
      setBusyId(null);
    }
  }

  const filtered = users.filter((u) => u.email.toLowerCase().includes(search.toLowerCase()) || (u.full_name || "").toLowerCase().includes(search.toLowerCase()));
  const admins = filtered.filter((u) => u.role === "admin");
  const employees = filtered.filter((u) => u.role !== "admin");
  const pending = filtered.filter((u) => u.status === "invited");

  if (loading) {
    return <div style={{ minHeight: "60vh", display: "flex", alignItems: "center", justifyContent: "center" }}><div className="spinner" style={{ width: 22, height: 22, borderTopColor: "var(--accent-primary)", borderColor: "var(--border-card)" }} /></div>;
  }

  return (
    <div className="app-container">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 14, marginBottom: 22 }}>
        <div>
          <h1 style={{ fontSize: 22, marginBottom: 4 }}>Team</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13.5 }}>{users.length} member{users.length === 1 ? "" : "s"}</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link href="/admin/analytics" className="btn btn-secondary"><Icon name="chart" size={15} /> Analytics</Link>
          <button onClick={() => setShowModal(true)} className="btn btn-primary"><Icon name="plus" size={15} /> Add member</button>
        </div>
      </div>

      {error && <div className="alert-box alert-error"><Icon name="alert" size={16} />{error}</div>}
      {success && <div className="alert-box alert-success"><Icon name="check" size={16} />{success}</div>}

      <div className="stats-grid" style={{ marginBottom: 22 }}>
        <div className="stat-card">
          <div className="stat-header"><span className="stat-label">Total members</span><Icon name="users" size={14} className="stat-icon" /></div>
          <span className="stat-value">{users.length}</span>
        </div>
        <div className="stat-card">
          <div className="stat-header"><span className="stat-label">Admins</span><Icon name="shield" size={14} className="stat-icon" /></div>
          <span className="stat-value">{admins.length}</span>
        </div>
        <div className="stat-card">
          <div className="stat-header"><span className="stat-label">Employees</span><Icon name="user" size={14} className="stat-icon" /></div>
          <span className="stat-value">{employees.length}</span>
        </div>
        <div className="stat-card">
          <div className="stat-header"><span className="stat-label">Pending invites</span><Icon name="mail" size={14} className="stat-icon" /></div>
          <span className="stat-value">{pending.length}</span>
        </div>
      </div>

      <div style={{ position: "relative", marginBottom: 16 }}>
        <input type="text" className="form-input" style={{ paddingLeft: 34 }} placeholder="Search by name or email…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <span style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--text-dim)" }}><Icon name="search" size={14} /></span>
      </div>

      <div className="glass-panel" style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Member</th>
                <th>Role</th>
                <th>Status</th>
                <th>Meetings</th>
                <th>Open tasks</th>
                <th>Overdue</th>
                <th>Joined</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((user) => (
                <tr key={user.id} style={{ opacity: busyId === user.id ? 0.5 : 1 }}>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span className="avatar" style={{ width: 32, height: 32, fontSize: 12 }}>{initials(user.full_name || user.email)}</span>
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 13.5 }}>{user.full_name || "—"}</div>
                        <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{user.email}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className={`badge ${user.role === "admin" ? "badge-purple" : "badge-cyan"}`}>
                      <Icon name={user.role === "admin" ? "shield" : "user"} size={10} /> {user.role === "admin" ? "Admin" : "Employee"}
                    </span>
                  </td>
                  <td>
                    {user.status === "invited"
                      ? <span className="badge badge-amber"><Icon name="clock" size={10} /> Invited</span>
                      : <span className="badge badge-emerald"><Icon name="check" size={10} /> Active</span>}
                  </td>
                  <td>{user.meeting_count}</td>
                  <td>{user.open_tasks}</td>
                  <td style={{ color: user.overdue_tasks > 0 ? "var(--accent-rose)" : undefined, fontWeight: user.overdue_tasks > 0 ? 700 : 400 }}>{user.overdue_tasks}</td>
                  <td style={{ color: "var(--text-muted)" }}>{formatDate(user.created_at, true)}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                      {user.status === "invited" && (
                        <button onClick={() => resendInvite(user)} disabled={busyId === user.id} className="btn btn-ghost btn-sm" title="Resend invite">
                          <Icon name="mail" size={12} />
                        </button>
                      )}
                      {user.id !== currentUserId && (
                        <button onClick={() => toggleRole(user)} disabled={busyId === user.id} className="btn btn-ghost btn-sm">
                          {user.role === "admin" ? "Make employee" : "Make admin"}
                        </button>
                      )}
                      {user.id !== currentUserId && (
                        <button onClick={() => removeUser(user)} disabled={busyId === user.id} className="icon-btn" style={{ width: 28, height: 28, color: "var(--accent-rose)" }} title="Remove">
                          <Icon name="trash" size={12} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={8} style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)" }}>No team members found.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showModal && (
        <InviteEmployeeModal
          onClose={() => setShowModal(false)}
          onInvited={() => { setSuccess("Invite sent."); loadUsers(); }}
        />
      )}
    </div>
  );
}
