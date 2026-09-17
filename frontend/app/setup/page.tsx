"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import Icon from "@/app/components/Icon";
import Waveform from "@/app/components/Waveform";

export default function SetupPage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api
      .needsSetup()
      .then((needed) => {
        if (!needed) {
          // Someone already set this workspace up — nothing to do here.
          router.replace("/login");
          return;
        }
        setChecking(false);
      })
      .catch(() => setChecking(false));
  }, [router]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (!fullName.trim() || !email || !password) {
      setError("Please fill in all fields.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setLoading(true);
    try {
      await api.setupFirstAdmin(email, password, fullName.trim());
      router.push("/admin");
    } catch (err: any) {
      setError(err?.message || "Setup failed.");
    } finally {
      setLoading(false);
    }
  };

  if (checking) return null;

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="brand-icon" style={{ width: 42, height: 42, margin: "0 auto 16px" }}>
          <Waveform size={20} active={false} />
        </div>
        <h1 style={{ fontSize: 20, textAlign: "center", marginBottom: 6 }}>Set up your workspace</h1>
        <p style={{ textAlign: "center", color: "var(--text-secondary)", fontSize: 13.5, marginBottom: 24 }}>
          This is a brand-new install — create the first account. It becomes the workspace admin automatically.
        </p>

        {error && (
          <div className="alert-box alert-error">
            <Icon name="alert" size={16} />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Your name</label>
            <input type="text" className="form-input" placeholder="e.g. Ali Khan" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
          </div>
          <div className="form-group">
            <label className="form-label">Email</label>
            <input type="email" className="form-input" placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="form-group">
            <label className="form-label">Password</label>
            <input type="password" className="form-input" placeholder="Minimum 8 characters" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={loading}>
            {loading ? "Setting up…" : "Create admin account"}
          </button>
        </form>
      </div>

      <style>{`
        .auth-shell {
          min-height: calc(100vh - 60px);
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 24px;
        }
        .auth-card {
          width: 100%;
          max-width: 400px;
          background: var(--bg-card);
          border: 1px solid var(--border-card);
          border-radius: var(--radius-lg);
          padding: 32px 28px;
          box-shadow: var(--shadow-lg);
        }
      `}</style>
    </div>
  );
}
