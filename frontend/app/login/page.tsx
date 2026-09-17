"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import Icon from "@/app/components/Icon";
import Waveform from "@/app/components/Waveform";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");

  useEffect(() => {
    // A brand-new install has no accounts at all — send whoever opens the
    // app straight to first-run setup instead of a login form with nothing
    // to log into.
    api.needsSetup().then((needed) => {
      if (needed) router.replace("/setup");
    }).catch(() => undefined);
  }, [router]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccessMsg("");

    if (!email || !password || (mode === "register" && !fullName.trim())) {
      setError("Please fill in all fields.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setLoading(true);
    try {
      if (mode === "register") {
        await api.register(email, password, fullName.trim());
        setSuccessMsg("Account created. Signing you in…");
      }
      const { user } = await api.login(email, password);
      router.push(user.role === "admin" ? "/admin" : "/dashboard");
    } catch (err: any) {
      setError(err?.message || "Authentication failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: "calc(100vh - 60px)", padding: 20 }}>
      <div className="glass-panel" style={{ width: "100%", maxWidth: 400, padding: "32px 30px" }}>
        <div style={{ textAlign: "center", marginBottom: 26 }}>
          <div className="brand-icon" style={{ width: 42, height: 42, borderRadius: 11, margin: "0 auto 16px" }}>
            <Waveform size={20} active />
          </div>
          <h2 style={{ fontSize: 20, marginBottom: 6 }}>{mode === "login" ? "Welcome back" : "Create your workspace"}</h2>
          <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
            {mode === "login" ? "Sign in to your meetings and tasks" : "Set up your meeting intelligence workspace"}
          </p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, background: "var(--bg-subtle)", padding: 4, borderRadius: "var(--radius-sm)", marginBottom: 22 }}>
          <button type="button" className={`btn btn-sm ${mode === "login" ? "btn-primary" : "btn-ghost"}`} onClick={() => { setMode("login"); setError(""); setSuccessMsg(""); }}>Sign in</button>
          <button type="button" className={`btn btn-sm ${mode === "register" ? "btn-primary" : "btn-ghost"}`} onClick={() => { setMode("register"); setError(""); setSuccessMsg(""); }}>Register</button>
        </div>

        {error && <div className="alert-box alert-error"><Icon name="alert" size={15} />{error}</div>}
        {successMsg && <div className="alert-box alert-success"><Icon name="check" size={15} />{successMsg}</div>}

        <form onSubmit={handleSubmit}>
          {mode === "register" && (
            <div className="form-group">
              <label className="form-label">Your name</label>
              <input type="text" className="form-input" placeholder="e.g. Ali Khan" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
              <p className="form-hint">Used so the assistant can match tasks spoken with your name to you.</p>
            </div>
          )}
          <div className="form-group">
            <label className="form-label">Email</label>
            <input type="email" className="form-input" placeholder="name@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="form-group" style={{ marginBottom: 22 }}>
            <label className="form-label">Password</label>
            <input type="password" className="form-input" placeholder="Minimum 8 characters" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={loading}>
            {loading ? (
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}><span className="spinner" /> {mode === "login" ? "Signing in…" : "Creating account…"}</span>
            ) : mode === "login" ? "Sign in" : "Create workspace"}
          </button>
        </form>

        <div style={{ textAlign: "center", fontSize: 12.5, color: "var(--text-secondary)", marginTop: 18 }}>
          {mode === "login" ? (
            <span>Don&apos;t have an account?{" "}
              <button type="button" onClick={() => { setMode("register"); setError(""); }} style={{ background: "none", border: "none", color: "var(--accent-primary)", fontWeight: 600, cursor: "pointer", padding: 0 }}>Register</button>
            </span>
          ) : (
            <span>Already have an account?{" "}
              <button type="button" onClick={() => { setMode("login"); setError(""); }} style={{ background: "none", border: "none", color: "var(--accent-primary)", fontWeight: 600, cursor: "pointer", padding: 0 }}>Sign in</button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
