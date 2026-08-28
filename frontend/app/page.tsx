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

  if (!mounted) return null;

  return (
    <div className="app-container">
      {/* Hero */}
      <section style={{ textAlign: "center", padding: "60px 20px 70px" }}>
        <h1
          style={{
            fontSize: "clamp(32px, 5vw, 52px)",
            lineHeight: 1.15,
            marginBottom: 18,
            maxWidth: 800,
            margin: "0 auto 18px",
            fontWeight: 600,
          }}
        >
          Automated meeting notes and structured action items.
        </h1>

        <p
          style={{
            fontSize: "clamp(15px, 2vw, 18px)",
            color: "var(--text-secondary)",
            maxWidth: 600,
            margin: "0 auto 32px",
            lineHeight: 1.6,
          }}
        >
          Fast local speech-to-text transcription, automated executive summaries, decision tracking, and task management.
        </p>

        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
          <Link href="/login" className="btn btn-primary" style={{ padding: "10px 22px" }}>
            Open Workspace
          </Link>
          <Link href="/login" className="btn btn-secondary" style={{ padding: "10px 22px" }}>
            Sign In
          </Link>
        </div>
      </section>

      {/* Feature Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
          gap: 16,
          marginBottom: 60,
        }}
      >
        <div className="glass-panel">
          <h3 style={{ fontSize: 16, marginBottom: 6 }}>Transcription</h3>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, lineHeight: 1.6 }}>
            Accurate speech-to-text with start and end timestamps, formatted cleanly per segment.
          </p>
        </div>

        <div className="glass-panel">
          <h3 style={{ fontSize: 16, marginBottom: 6 }}>Structured Analysis</h3>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, lineHeight: 1.6 }}>
            Automated extraction of executive summaries, key decisions, and discussion highlights.
          </p>
        </div>

        <div className="glass-panel">
          <h3 style={{ fontSize: 16, marginBottom: 6 }}>Action Items</h3>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, lineHeight: 1.6 }}>
            Assignees and deadlines extracted directly into an interactive task tracker.
          </p>
        </div>
      </div>
    </div>
  );
}
