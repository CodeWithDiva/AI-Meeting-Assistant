"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { authStorage } from "@/lib/api";

export default function LandingPage() {
  const router = useRouter();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    if (authStorage.isLoggedIn()) {
      router.push("/dashboard");
    }
  }, [router]);

  return (
    <div className="app-container">
      {/* Hero Section */}
      <section style={{ textAlign: "center", padding: "80px 20px 80px" }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginBottom: 20 }}>
          <span className="badge badge-indigo">ENTERPRISE MEETING INTELLIGENCE</span>
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>•</span>
          <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>Faster-Whisper + Autonomous Agent v3</span>
        </div>

        <h1
          style={{
            fontSize: "clamp(34px, 5.5vw, 58px)",
            lineHeight: 1.15,
            marginBottom: 22,
            maxWidth: 860,
            margin: "0 auto 22px",
            fontWeight: 800,
            letterSpacing: "-0.04em",
          }}
        >
          Automated meeting transcripts, executive notes, and assigned tasks.
        </h1>

        <p
          style={{
            fontSize: "clamp(16px, 2vw, 19px)",
            color: "var(--text-secondary)",
            maxWidth: 680,
            margin: "0 auto 36px",
            lineHeight: 1.6,
          }}
        >
          Autonomous meeting copilot that connects to your Zoom & Google Meet sessions, records live speech, identifies speakers, extracts key decisions, and assigns action items directly to your team.
        </p>

        <div style={{ display: "flex", gap: 14, justifyContent: "center", flexWrap: "wrap" }}>
          <Link href="/login" className="btn btn-primary btn-lg">
            <span>⚡ Open Workspace</span>
          </Link>
          <Link href="/login" className="btn btn-secondary btn-lg">
            <span>Sign In →</span>
          </Link>
        </div>
      </section>

      {/* Feature Showcase Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 20,
          marginBottom: 70,
        }}
      >
        <div className="glass-panel">
          <div style={{ fontSize: 28, marginBottom: 14 }}>🎙️</div>
          <h3 style={{ fontSize: 18, marginBottom: 8, color: "#fff" }}>Real-Time Transcription</h3>
          <p style={{ color: "var(--text-secondary)", fontSize: 14, lineHeight: 1.6 }}>
            Accurate speech-to-text with millisecond timestamps and speaker identification powered by faster-whisper.
          </p>
        </div>

        <div className="glass-panel">
          <div style={{ fontSize: 28, marginBottom: 14 }}>⚡</div>
          <h3 style={{ fontSize: 18, marginBottom: 8, color: "#fff" }}>Structured AI Analysis</h3>
          <p style={{ color: "var(--text-secondary)", fontSize: 14, lineHeight: 1.6 }}>
            Automated synthesis of executive summaries, approved conclusions, and key discussion highlights.
          </p>
        </div>

        <div className="glass-panel">
          <div style={{ fontSize: 28, marginBottom: 14 }}>🎯</div>
          <h3 style={{ fontSize: 18, marginBottom: 8, color: "#fff" }}>Autonomous Task Assignment</h3>
          <p style={{ color: "var(--text-secondary)", fontSize: 14, lineHeight: 1.6 }}>
            Automatically extract assignees, assigners, tasks, and deadlines into an interactive action-item board.
          </p>
        </div>
      </div>
    </div>
  );
}
