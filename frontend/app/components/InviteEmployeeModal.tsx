"use client";

import { FormEvent, useState } from "react";
import { InviteResult, api } from "@/lib/api";
import Icon from "./Icon";

/**
 * Add-a-team-member modal used on both /admin and /admin/team.
 *
 * Admins never set anyone else's password — they give a name and email, the
 * system creates the account and hands back a one-time setup link. If
 * SMTP_HOST is configured that link is also emailed; either way it's shown
 * here so the admin can send it themselves (WhatsApp, Slack, in person) when
 * email isn't set up.
 */
export default function InviteEmployeeModal({
  onClose,
  onInvited,
  allowRoleChoice = true,
}: {
  onClose: () => void;
  onInvited: () => void;
  allowRoleChoice?: boolean;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "employee">("employee");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<InviteResult | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || !email.trim()) {
      setError("Name and email are required.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const invite = await api.adminInviteUser({ email: email.trim(), full_name: name.trim(), role });
      setResult(invite);
      onInvited();
    } catch (err: any) {
      setError(err?.message || "Could not add that person.");
    } finally {
      setSubmitting(false);
    }
  }

  function copyLink() {
    if (!result) return;
    navigator.clipboard.writeText(result.invite_link);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ fontSize: 17 }}>{result ? "Invite sent" : "Add a team member"}</h3>
          <button onClick={onClose} className="icon-btn" style={{ border: "none" }}><Icon name="x" size={16} /></button>
        </div>

        {!result ? (
          <>
            <p style={{ fontSize: 12.5, color: "var(--text-muted)", marginBottom: 18, lineHeight: 1.5 }}>
              They set their own password — you only need their name and email.
            </p>
            {error && <div className="alert-box alert-error"><Icon name="alert" size={15} />{error}</div>}
            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label className="form-label">Full name</label>
                <input type="text" className="form-input" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
              </div>
              <div className="form-group" style={{ marginBottom: allowRoleChoice ? 16 : 22 }}>
                <label className="form-label">Email</label>
                <input type="email" className="form-input" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </div>
              {allowRoleChoice && (
                <div className="form-group" style={{ marginBottom: 22 }}>
                  <label className="form-label">Role</label>
                  <select className="form-input" value={role} onChange={(e) => setRole(e.target.value as "admin" | "employee")}>
                    <option value="employee">Employee</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
              )}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                <button type="button" className="btn btn-secondary btn-sm" onClick={onClose} disabled={submitting}>Cancel</button>
                <button type="submit" className="btn btn-primary btn-sm" disabled={submitting}>{submitting ? "Adding…" : "Add & send invite"}</button>
              </div>
            </form>
          </>
        ) : (
          <div>
            <div className="alert-box alert-success" style={{ marginBottom: 16 }}>
              <Icon name="check" size={16} />
              {result.email_sent
                ? `An email was sent to ${result.user.email} with a link to set their password.`
                : "Email isn't configured on this server — share this link with them directly."}
            </div>
            <label className="form-label">Setup link</label>
            <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
              <input type="text" className="form-input mono" readOnly value={result.invite_link} style={{ fontSize: 12 }} />
              <button type="button" onClick={copyLink} className="btn btn-secondary btn-sm" style={{ flexShrink: 0 }}>
                <Icon name={copied ? "check" : "link"} size={13} /> {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <button type="button" onClick={onClose} className="btn btn-primary btn-block">Done</button>
          </div>
        )}
      </div>
    </div>
  );
}
