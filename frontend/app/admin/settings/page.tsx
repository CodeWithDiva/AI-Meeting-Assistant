"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, authStorage, SystemCapabilities } from "@/lib/api";

interface SystemConfig {
  label: string;
  key: string;
  value: string;
  description: string;
  editable: boolean;
  icon: string;
}

export default function AdminSettingsPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  // Read from the server rather than hardcoded, so this page shows what is
  // actually running instead of what the defaults used to be.
  const [caps, setCaps] = useState<SystemCapabilities | null>(null);

  useEffect(() => {
    if (!authStorage.isLoggedIn()) { router.push("/login"); return; }
    api.getMe().then((me) => {
      if (me.role !== "admin") { router.push("/dashboard"); return; }
      api.getSystemCapabilities().then(setCaps).catch(() => undefined);
      setLoading(false);
    }).catch(() => router.push("/login"));
  }, [router]);

  const installed = (ok: boolean | undefined, missingHint: string) =>
    ok === undefined ? "Unknown" : ok ? "Installed ✓" : `Not installed — ${missingHint}`;

  const configs: SystemConfig[] = [
    {
      label: "Admin Emails",
      key: "ADMIN_EMAILS",
      value: "Set in root .env file",
      description: "Comma-separated list of emails that get admin role on registration. Requires backend restart to take effect.",
      editable: false,
      icon: "🔑",
    },
    {
      label: "Whisper Model",
      key: "WHISPER_MODEL",
      value: caps?.whisper_model ?? "…",
      description: "Faster-Whisper model size: tiny, base, small, medium, large-v2. 'small' is the realistic floor for Urdu; 'base' mangles it.",
      editable: false,
      icon: "🎤",
    },
    {
      label: "Whisper CPU Threads",
      key: "WHISPER_CPU_THREADS",
      value: "4",
      description: "Number of CPU threads used for Whisper transcription. Increase for faster processing on multi-core machines.",
      editable: false,
      icon: "⚙️",
    },
    {
      label: "Ollama Base URL",
      key: "OLLAMA_BASE_URL",
      value: "http://localhost:11434",
      description: "Ollama server URL for LLM-powered meeting analysis and Ava voice replies.",
      editable: false,
      icon: "🤖",
    },
    {
      label: "Piper TTS Path",
      key: "PIPER_PATH",
      value: "Not configured (using pyttsx3 fallback)",
      description: "Path to Piper TTS binary for high-quality voice synthesis. Download from https://github.com/rhasspy/piper",
      editable: false,
      icon: "🔊",
    },
    {
      label: "Piper Model",
      key: "PIPER_MODEL",
      value: "Not configured",
      description: "Path to .onnx voice model file for Piper TTS. e.g. en_US-lessac-medium.onnx",
      editable: false,
      icon: "🗣️",
    },
    {
      label: "LLM Model",
      key: "OLLAMA_MODEL",
      value: caps?.llm_model ?? "…",
      description: "Ollama model used for notes, decisions and task extraction. qwen2.5:7b handles Urdu far better than llama3.2:3b.",
      editable: false,
      icon: "🧠",
    },
    {
      label: "Meeting Platforms",
      key: "PLATFORMS",
      value: (caps?.platforms ?? []).join(", ") || "…",
      description: "Platforms the assistant's own browser agent can join. No vendor app, OAuth or webhook is used.",
      editable: false,
      icon: "📹",
    },
    {
      label: "Browser Automation",
      key: "PLAYWRIGHT",
      value: installed(caps?.browser_automation, "run `playwright install chromium`"),
      description: "Required for the assistant to actually join meetings. Without it, joins fall back to simulated mode.",
      editable: false,
      icon: "🌐",
    },
    {
      label: "Virtual Audio Devices",
      key: "SOUNDDEVICE",
      value: installed(caps?.audio_devices, "install sounddevice + a virtual audio cable"),
      description: "Required to hear the meeting and to speak Ava's replies into it. See docs/browser-bot-setup.md.",
      editable: false,
      icon: "🎚️",
    },
    {
      label: "Database URL",
      key: "DATABASE_URL",
      value: "SQLite (local) — meetings.db",
      description: "Database connection string. Leave blank to use SQLite. Set PostgreSQL URL for production.",
      editable: false,
      icon: "🗄️",
    },
  ];

  const envTemplate = `# AI Meeting Assistant — Environment Variables
# Place this file at: AI-Meeting-Assistant/.env

# Application
APP_NAME=AI Meeting Assistant
DEBUG=True

# Database (blank = SQLite)
DATABASE_URL=

# Security
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# AI (Ollama)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

# Whisper (Urdu + English)
WHISPER_MODEL=small
WHISPER_CPU_THREADS=4
# Blank = auto-detect Urdu vs English, then lock onto it for the meeting.
WHISPER_LANGUAGE=

# Meeting bot — joins Zoom / Google Meet through its own browser.
# No Zoom Marketplace app, OAuth or RTMS webhook is needed.
BOT_DISPLAY_NAME=Ava Notetaker
BOT_HEADLESS=False
BOT_JOIN_TIMEOUT_SECONDS=90
BOT_UI_TIMEOUT_SECONDS=20
BOT_MIC_CAPTURE_DEVICE=
BOT_SPEAKER_PLAYBACK_DEVICE=

# Admin
ADMIN_EMAILS=admin@yourcompany.com,another@yourcompany.com

# Piper TTS (optional — high quality voice)
# PIPER_PATH=C:/piper/piper.exe
# PIPER_MODEL=C:/piper/models/en_US-lessac-medium.onnx`;

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
        <h1 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, background: "linear-gradient(135deg, #f59e0b, #ef4444)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
          System Settings
        </h1>
        <span style={{ marginLeft: "auto", padding: "0.25rem 0.75rem", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: "9999px", fontSize: "0.75rem", color: "#f87171" }}>
          Admin Only
        </span>
      </header>

      <div style={{ maxWidth: "900px", margin: "0 auto", padding: "2rem" }}>
        {/* Info banner */}
        <div style={{ background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.3)", borderRadius: "0.75rem", padding: "1rem 1.25rem", marginBottom: "2rem", display: "flex", gap: "0.75rem", alignItems: "flex-start" }}>
          <span style={{ fontSize: "1.1rem", flexShrink: 0 }}>ℹ️</span>
          <div style={{ fontSize: "0.875rem", color: "var(--text-secondary)" }}>
            Settings are configured via the <strong style={{ color: "var(--text-primary)" }}>root .env</strong> file. After changing any setting, restart the backend server.
            New settings take effect on next startup.
          </div>
        </div>

        {/* Config cards */}
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginBottom: "2.5rem" }}>
          <h2 style={{ margin: "0 0 0.75rem 0", fontSize: "1rem", fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Configuration</h2>
          {configs.map((cfg) => (
            <div key={cfg.key} style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: "0.875rem", padding: "1.125rem 1.25rem", display: "flex", alignItems: "flex-start", gap: "1rem" }}>
              <span style={{ fontSize: "1.25rem", flexShrink: 0, marginTop: "0.1rem" }}>{cfg.icon}</span>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap", marginBottom: "0.35rem" }}>
                  <span style={{ fontWeight: 600, fontSize: "0.9rem" }}>{cfg.label}</span>
                  <code style={{ fontSize: "0.75rem", padding: "0.15rem 0.45rem", background: "var(--bg-glass)", borderRadius: "0.25rem", color: "var(--accent-cyan)", fontFamily: "monospace" }}>{cfg.key}</code>
                </div>
                <div style={{ fontSize: "0.85rem", color: "var(--accent-emerald)", fontWeight: 500, marginBottom: "0.35rem" }}>{cfg.value}</div>
                <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", lineHeight: 1.5 }}>{cfg.description}</div>
              </div>
            </div>
          ))}
        </div>

        {/* .env template */}
        <div>
          <h2 style={{ margin: "0 0 1rem 0", fontSize: "1rem", fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            .env Template
          </h2>
          <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: "1rem", overflow: "hidden" }}>
            <div style={{ background: "var(--bg-glass)", padding: "0.75rem 1.25rem", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid var(--border-subtle)" }}>
              <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>📄 .env</span>
              <button
                onClick={() => navigator.clipboard.writeText(envTemplate)}
                style={{ fontSize: "0.78rem", padding: "0.3rem 0.7rem", background: "var(--bg-primary)", border: "1px solid var(--border-subtle)", borderRadius: "0.4rem", color: "var(--text-secondary)", cursor: "pointer" }}
              >
                Copy
              </button>
            </div>
            <pre style={{ margin: 0, padding: "1.25rem", fontSize: "0.8rem", lineHeight: 1.7, overflowX: "auto", color: "var(--text-secondary)", fontFamily: "monospace" }}>
              {envTemplate}
            </pre>
          </div>
        </div>

        {/* Piper TTS install guide */}
        <div style={{ marginTop: "2rem", background: "rgba(34,211,238,0.05)", border: "1px solid rgba(34,211,238,0.15)", borderRadius: "1rem", padding: "1.5rem" }}>
          <h3 style={{ margin: "0 0 1rem 0", fontSize: "1rem", fontWeight: 600, color: "var(--accent-cyan)" }}>🔊 Piper TTS Setup (Optional)</h3>
          <p style={{ margin: "0 0 0.75rem 0", fontSize: "0.875rem", color: "var(--text-secondary)", lineHeight: 1.6 }}>
            Piper provides high-quality, offline voice synthesis for Ava&apos;s voice replies. Without it, the system falls back to pyttsx3.
          </p>
          <ol style={{ margin: "0 0 1rem 0", paddingLeft: "1.25rem", fontSize: "0.875rem", color: "var(--text-secondary)", lineHeight: 2 }}>
            <li>Download Piper from <a href="https://github.com/rhasspy/piper/releases" target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent-cyan)" }}>github.com/rhasspy/piper</a></li>
            <li>Extract the binary (piper.exe on Windows)</li>
            <li>Download a voice model (.onnx file) from the Piper voices list</li>
            <li>Set <code style={{ background: "var(--bg-glass)", padding: "0.1rem 0.35rem", borderRadius: "0.25rem", fontFamily: "monospace" }}>PIPER_PATH</code> and <code style={{ background: "var(--bg-glass)", padding: "0.1rem 0.35rem", borderRadius: "0.25rem", fontFamily: "monospace" }}>PIPER_MODEL</code> in .env</li>
            <li>Restart the backend</li>
          </ol>
        </div>
      </div>
    </div>
  );
}
