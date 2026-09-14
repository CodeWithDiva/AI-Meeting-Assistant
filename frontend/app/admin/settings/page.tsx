"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, authStorage, SystemCapabilities } from "@/lib/api";
import Icon, { IconName } from "@/app/components/Icon";

interface SystemConfig {
  label: string;
  key: string;
  value: string;
  description: string;
  icon: IconName;
  ok?: boolean;
}

export default function AdminSettingsPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [caps, setCaps] = useState<SystemCapabilities | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!authStorage.isLoggedIn()) { router.push("/login"); return; }
    api.getMe().then((me) => {
      if (me.role !== "admin") { router.push("/dashboard"); return; }
      api.getSystemCapabilities().then(setCaps).catch(() => undefined);
      setLoading(false);
    }).catch(() => router.push("/login"));
  }, [router]);

  const installed = (ok: boolean | undefined, missingHint: string) =>
    ok === undefined ? "Unknown" : ok ? "Installed" : `Not installed — ${missingHint}`;

  const configs: SystemConfig[] = [
    {
      label: "Assistant name",
      key: "BOT_DISPLAY_NAME",
      value: caps?.assistant_name ?? "…",
      description: "The name the bot joins meetings under, and the wake word it responds to.",
      icon: "radio",
      ok: true,
    },
    {
      label: "Wake word",
      key: "BOT_WAKE_WORD",
      value: caps?.wake_word ?? "…",
      description: "Say this name in the meeting to get a spoken answer. Defaults to the first word of the assistant's name.",
      icon: "mic",
      ok: true,
    },
    {
      label: "Meeting platforms",
      key: "PLATFORMS",
      value: (caps?.platforms ?? []).map((p) => (p === "google_meet" ? "Google Meet" : p[0].toUpperCase() + p.slice(1))).join(", ") || "…",
      description: "Platforms the assistant's own browser agent can join directly by link. No vendor app, OAuth or webhook is used.",
      icon: "video",
      ok: true,
    },
    {
      label: "Browser automation",
      key: "PLAYWRIGHT",
      value: installed(caps?.browser_automation, "run `playwright install chromium`"),
      description: "Required for the assistant to actually join meetings. Without it, joins fall back to simulated mode.",
      icon: "external",
      ok: caps?.browser_automation,
    },
    {
      label: "Meeting audio capture",
      key: "SOUNDDEVICE",
      value: installed(caps?.audio_devices, "install sounddevice + a virtual audio cable"),
      description: "Required to hear the meeting. See docs/browser-bot-setup.md.",
      icon: "volume",
      ok: caps?.audio_devices,
    },
    {
      label: "Spoken replies reach the meeting",
      key: "BOT_VIRTUAL_MIC_LABEL",
      value: caps?.virtual_microphone ? "Configured" : "Not configured — replies stay in the dashboard only",
      description: "A virtual microphone cable so the assistant's TTS answer is heard by everyone, not just played locally.",
      icon: "mic",
      ok: caps?.virtual_microphone,
    },
    {
      label: "Transcription (Whisper)",
      key: "WHISPER_MODEL",
      value: caps ? `${installed(caps.transcription, "install faster-whisper")} · model: ${caps.whisper_model}` : "…",
      description: "faster-whisper model size: tiny, base, small, medium, large-v2. 'small' is the realistic floor for Urdu.",
      icon: "message",
      ok: caps?.transcription,
    },
    {
      label: "LLM (notes, decisions, Q&A)",
      key: "OLLAMA_MODEL",
      value: caps?.llm_model ?? "…",
      description: "Ollama model used for notes, decisions, task extraction and the meeting chat copilot.",
      icon: "layers",
      ok: true,
    },
    {
      label: "Task email notifications",
      key: "SMTP_HOST",
      value: caps?.email_notifications ? "Configured — assignees get an email too" : "Not configured — in-app notifications only",
      description: "Set SMTP_HOST in .env to also email a task's assignee with the deadline and a calendar invite.",
      icon: "mail",
      ok: caps?.email_notifications,
    },
    {
      label: "Text-to-speech",
      key: "TTS",
      value: installed(caps?.tts, "pip install pyttsx3, or configure Piper"),
      description: "Used for the assistant's spoken meeting replies.",
      icon: "volume",
      ok: caps?.tts,
    },
  ];

  const envTemplate = `# AI Meeting Assistant — Environment Variables
# Place this file at: AI-Meeting-Assistant/.env

BOT_DISPLAY_NAME=Alina
BOT_HEADLESS=False

# Virtual audio cable so spoken replies reach everyone in the meeting
BOT_SPEAKER_PLAYBACK_DEVICE=CABLE Input (VB-Audio Virtual Cable)
BOT_VIRTUAL_MIC_LABEL=CABLE Output (VB-Audio Virtual Cable)

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

WHISPER_MODEL=small
WHISPER_LANGUAGE=

ADMIN_EMAILS=admin@yourcompany.com

# Task email notifications (optional)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@yourcompany.com
SMTP_PASSWORD=your-app-password
TASK_REMINDER_HOURS=24`;

  if (loading) {
    return <div style={{ minHeight: "60vh", display: "flex", alignItems: "center", justifyContent: "center" }}><div className="spinner" style={{ width: 22, height: 22, borderTopColor: "var(--accent-primary)", borderColor: "var(--border-card)" }} /></div>;
  }

  return (
    <div className="app-container">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 14, marginBottom: 22 }}>
        <div>
          <h1 style={{ fontSize: 22, marginBottom: 4 }}>System settings</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13.5 }}>What&apos;s actually running on this server, right now.</p>
        </div>
        <span className="badge badge-rose"><Icon name="shield" size={11} /> Admin only</span>
      </div>

      <div className="alert-box alert-info">
        <Icon name="info" size={16} />
        Settings are configured in the root <code style={{ margin: "0 4px" }}>.env</code> file. Restart the backend after changing any of them.
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 28 }}>
        {configs.map((cfg) => (
          <div key={cfg.key} className="glass-panel" style={{ display: "flex", alignItems: "flex-start", gap: 14, padding: "15px 18px" }}>
            <div style={{ width: 34, height: 34, borderRadius: "var(--radius-sm)", background: cfg.ok === false ? "var(--tint-amber)" : "var(--bg-subtle)", color: cfg.ok === false ? "var(--accent-amber)" : "var(--text-secondary)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <Icon name={cfg.icon} size={16} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13.5 }}>{cfg.label}</span>
                <code style={{ fontSize: 11, padding: "2px 6px", background: "var(--bg-subtle)", borderRadius: 4, color: "var(--accent-indigo)" }}>{cfg.key}</code>
              </div>
              <div style={{ fontSize: 13, color: cfg.ok === false ? "var(--accent-amber)" : "var(--accent-emerald)", fontWeight: 500, marginBottom: 3 }}>{cfg.value}</div>
              <div style={{ fontSize: 12.5, color: "var(--text-muted)", lineHeight: 1.5 }}>{cfg.description}</div>
            </div>
          </div>
        ))}
      </div>

      <div>
        <h2 style={{ fontSize: 14, marginBottom: 12, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>.env template</h2>
        <div className="glass-panel" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ background: "var(--bg-subtle)", padding: "10px 16px", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid var(--border-subtle)" }}>
            <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>.env</span>
            <button
              onClick={() => { navigator.clipboard.writeText(envTemplate); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
              className="btn btn-secondary btn-sm"
            >
              <Icon name={copied ? "check" : "fileText"} size={12} /> {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <pre style={{ margin: 0, padding: 18, fontSize: 12.5, lineHeight: 1.7, overflowX: "auto", color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>{envTemplate}</pre>
        </div>
      </div>

      <div style={{ marginTop: 20, display: "flex", gap: 12 }}>
        <Link href="/admin/team" className="btn btn-secondary"><Icon name="users" size={15} /> Team</Link>
        <Link href="/admin/analytics" className="btn btn-secondary"><Icon name="chart" size={15} /> Analytics</Link>
      </div>
    </div>
  );
}
