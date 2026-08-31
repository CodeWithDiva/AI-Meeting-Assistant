"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccessMsg("");

    if (!email || !password) {
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
        await api.register(email, password);
        setSuccessMsg("Account created successfully. Authenticating...");
      }
      await api.login(email, password);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err?.message || "Authentication failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        minHeight: "calc(100vh - 180px)",
        padding: "20px",
      }}
    >
      <div
        className="glass-panel"
        style={{
          width: "100%",
          maxWidth: 420,
          padding: "36px 32px",
          margin: "0 auto",
          border: "1px solid var(--border-card-hover)",
          boxShadow: "var(--shadow-lg), 0 0 40px rgba(99, 102, 241, 0.15)",
        }}
      >
        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 26 }}>
          <div
            style={{
              width: 44,
              height: 44,
              background: "var(--accent-gradient)",
              borderRadius: "var(--radius-sm)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 20,
              margin: "0 auto 14px",
              boxShadow: "0 0 20px rgba(99, 102, 241, 0.4)",
            }}
          >
            ⚡
          </div>
          <h2 style={{ fontSize: 22, marginBottom: 6, color: "#ffffff" }}>
            {mode === "login" ? "Welcome Back" : "Create Workspace"}
          </h2>
          <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
            {mode === "login"
              ? "Sign in to access your meeting transcripts and tasks"
              : "Set up your autonomous meeting intelligence workspace"}
          </p>
        </div>

        {/* Tab switch */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 4,
            background: "var(--bg-input)",
            padding: 4,
            borderRadius: "var(--radius-sm)",
            marginBottom: 24,
            border: "1px solid var(--border-subtle)",
          }}
        >
          <button
            type="button"
            className="btn btn-sm"
            style={{
              background: mode === "login" ? "rgba(99, 102, 241, 0.2)" : "transparent",
              color: mode === "login" ? "#ffffff" : "var(--text-secondary)",
              border: mode === "login" ? "1px solid rgba(99, 102, 241, 0.4)" : "1px solid transparent",
              fontWeight: mode === "login" ? 700 : 500,
            }}
            onClick={() => {
              setMode("login");
              setError("");
              setSuccessMsg("");
            }}
          >
            Sign In
          </button>
          <button
            type="button"
            className="btn btn-sm"
            style={{
              background: mode === "register" ? "rgba(99, 102, 241, 0.2)" : "transparent",
              color: mode === "register" ? "#ffffff" : "var(--text-secondary)",
              border: mode === "register" ? "1px solid rgba(99, 102, 241, 0.4)" : "1px solid transparent",
              fontWeight: mode === "register" ? 700 : 500,
            }}
            onClick={() => {
              setMode("register");
              setError("");
              setSuccessMsg("");
            }}
          >
            Register
          </button>
        </div>

        {/* Alerts */}
        {error && <div className="alert-box alert-error">{error}</div>}
        {successMsg && <div className="alert-box alert-success">{successMsg}</div>}

        {/* Form */}
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Work Email</label>
            <input
              type="email"
              className="form-input"
              placeholder="name@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="form-group" style={{ marginBottom: 24 }}>
            <label className="form-label">Password</label>
            <input
              type="password"
              className="form-input"
              placeholder="Minimum 8 characters"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: "100%", padding: "12px", marginBottom: 16 }}
            disabled={loading}
          >
            {loading ? (
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span className="spinner" />
                <span>{mode === "login" ? "Signing In..." : "Creating Account..."}</span>
              </span>
            ) : mode === "login" ? (
              "Sign In to Workspace"
            ) : (
              "Create Workspace Account"
            )}
          </button>
        </form>

        <div style={{ textAlign: "center", fontSize: 13, color: "var(--text-secondary)" }}>
          {mode === "login" ? (
            <span>
              Don&apos;t have an account?{" "}
              <button
                type="button"
                onClick={() => {
                  setMode("register");
                  setError("");
                }}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--accent-indigo)",
                  fontWeight: 600,
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                Register here
              </button>
            </span>
          ) : (
            <span>
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => {
                  setMode("login");
                  setError("");
                }}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--accent-indigo)",
                  fontWeight: 600,
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                Sign In
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
