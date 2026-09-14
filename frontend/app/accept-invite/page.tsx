"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { api, InviteDetails } from "@/lib/api";
import Icon from "@/app/components/Icon";

function AcceptInviteForm() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") || "";

  const [invite, setInvite] = useState<InviteDetails | null>(null);
  const [checking, setChecking] = useState(true);
  const [invalid, setInvalid] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!token) { setInvalid(true); setChecking(false); return; }
    api.getInvite(token).then(setInvite).catch(() => setInvalid(true)).finally(() => setChecking(false));
  }, [token]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 8) { setError("Password must be at least 8 characters."); return; }
    if (password !== confirm) { setError("Passwords don't match."); return; }

    setSubmitting(true);
    try {
      const { user } = await api.acceptInvite(token, password);
      router.push(user.role === "admin" ? "/admin" : "/dashboard");
    } catch (err: any) {
      setError(err?.message || "Could not set up your account.");
    } finally {
      setSubmitting(false);
    }
  }

  if (checking) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: "calc(100vh - 60px)" }}>
        <div className="spinner" style={{ width: 22, height: 22, borderTopColor: "var(--accent-primary)", borderColor: "var(--border-card)" }} />
      </div>
    );
  }

  if (invalid || !invite) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: "calc(100vh - 60px)", padding: 20 }}>
        <div className="glass-panel empty-state" style={{ maxWidth: 420 }}>
          <div className="icon-wrap"><Icon name="alert" size={20} /></div>
          <h4>This invite link is invalid or has expired</h4>
          <p>Ask whoever added you to the workspace to resend your invite.</p>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: "calc(100vh - 60px)", padding: 20 }}>
      <div className="glass-panel" style={{ width: "100%", maxWidth: 400, padding: "32px 30px" }}>
        <div style={{ textAlign: "center", marginBottom: 26 }}>
          <div className="brand-icon" style={{ width: 42, height: 42, borderRadius: 11, margin: "0 auto 16px" }}>
            <Icon name="mail" size={19} />
          </div>
          <h2 style={{ fontSize: 20, marginBottom: 6 }}>Welcome{invite.full_name ? `, ${invite.full_name.split(" ")[0]}` : ""}</h2>
          <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
            Set a password for <strong style={{ color: "var(--text-primary)" }}>{invite.email}</strong> to finish joining the workspace.
          </p>
        </div>

        {error && <div className="alert-box alert-error"><Icon name="alert" size={15} />{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Choose a password</label>
            <input type="password" className="form-input" placeholder="Minimum 8 characters" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus required />
          </div>
          <div className="form-group" style={{ marginBottom: 22 }}>
            <label className="form-label">Confirm password</label>
            <input type="password" className="form-input" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
          </div>
          <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={submitting}>
            {submitting ? <span style={{ display: "flex", alignItems: "center", gap: 8 }}><span className="spinner" /> Setting up…</span> : "Set password & sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={null}>
      <AcceptInviteForm />
    </Suspense>
  );
}
