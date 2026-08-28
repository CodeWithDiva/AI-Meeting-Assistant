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
        setSuccessMsg("Account created. Signing in...");
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
        minHeight: "calc(100vh - 160px)",
        padding: "20px",
      }}
    >
      <div
        className="glass-panel"
        style={{
          width: "100%",
          maxWidth: 400,
          padding: "32px 28px",
          margin: "0 auto",
        }}
      >
        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <h2 style={{ fontSize: 20, marginBottom: 4 }}>
            {mode === "login" ? "Sign In" : "Create Account"}
          </h2>
          <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
            {mode === "login"
              ? "Access your meeting workspaces and notes"
              : "Set up your workspace in seconds"}
          </p>
        </div>

        {/* Tab switch */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 4,
            background: "var(--bg-input)",
            padding: 3,
            borderRadius: "var(--radius-sm)",
            marginBottom: 20,
          }}
        >
          <button
            type="button"
            className="btn btn-sm"
            style={{
              background: mode === "login" ? "var(--bg-card)" : "transparent",
              color: mode === "login" ? "var(--text-primary)" : "var(--text-secondary)",
              border: mode === "login" ? "1px solid var(--border-subtle)" : "1px solid transparent",
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
              background: mode === "register" ? "var(--bg-card)" : "transparent",
              color: mode === "register" ? "var(--text-primary)" : "var(--text-secondary)",
              border: mode === "register" ? "1px solid var(--border-subtle)" : "1px solid transparent",
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
            <label className="form-label">Email</label>
            <input
              type="email"
              className="form-input"
              placeholder="name@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="form-group" style={{ marginBottom: 20 }}>
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
            style={{ width: "100%", padding: "10px", marginBottom: 14 }}
            disabled={loading}
          >
            {loading ? (
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span className="spinner"></span>
                <span>{mode === "login" ? "Signing In..." : "Creating Account..."}</span>
              </span>
            ) : mode === "login" ? (
              "Sign In"
            ) : (
              "Create Account"
            )}
          </button>
        </form>

        <div style={{ textAlign: "center", fontSize: 13, color: "var(--text-secondary)" }}>
          {mode === "login" ? (
            <span>
              New user?{" "}
              <button
                type="button"
                onClick={() => {
                  setMode("register");
                  setError("");
                }}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--accent-blue)",
                  fontWeight: 500,
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                Register here
              </button>
            </span>
          ) : (
            <span>
              Already registered?{" "}
              <button
                type="button"
                onClick={() => {
                  setMode("login");
                  setError("");
                }}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--accent-blue)",
                  fontWeight: 500,
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
