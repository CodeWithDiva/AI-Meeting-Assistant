"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { api, authStorage } from "@/lib/api";
import Icon, { IconName } from "@/app/components/Icon";
import Waveform from "@/app/components/Waveform";

const FEATURES: { icon: IconName; title: string; body: string }[] = [
  {
    icon: "mic",
    title: "Joins Zoom and Google Meet itself",
    body: "Paste a link — the assistant opens its own browser, joins by name, and starts listening. No Zoom Marketplace app, no OAuth, no admin approval needed.",
  },
  {
    icon: "message",
    title: "Urdu, English and Roman Urdu",
    body: "Transcribes mixed-language meetings live, with real speaker names read from the call — not guessed from audio.",
  },
  {
    icon: "checkSquare",
    title: "Tasks assigned to the right person",
    body: "Action items go to whoever the meeting names as responsible, not whoever was speaking — with deadlines, priority and reminders.",
  },
  {
    icon: "radio",
    title: "Answers when you call its name",
    body: "Ask a question out loud in the meeting and get a spoken answer, grounded in what was actually discussed.",
  },
];

export default function LandingPage() {
  const router = useRouter();

  useEffect(() => {
    if (!authStorage.isLoggedIn()) return;
    api.getMe().then((me) => router.push(me.role === "admin" ? "/admin" : "/dashboard")).catch(() => undefined);
  }, [router]);

  return (
    <div className="app-container">
      <section style={{ textAlign: "center", padding: "76px 12px 64px" }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 20, color: "var(--accent-primary)" }}>
          <Waveform size={30} active />
        </div>
        <span className="eyebrow" style={{ marginBottom: 18, display: "inline-flex" }}>
          <Icon name="layers" size={12} /> Meeting intelligence, run on your own machine
        </span>
        <h1 style={{ fontSize: "clamp(30px, 5vw, 46px)", lineHeight: 1.15, marginBottom: 20, maxWidth: 780, margin: "0 auto 20px" }}>
          One assistant that joins your meetings, writes the notes, and assigns the work.
        </h1>
        <p style={{ fontSize: "clamp(15px, 1.6vw, 17px)", color: "var(--text-secondary)", maxWidth: 620, margin: "0 auto 32px", lineHeight: 1.6 }}>
          A meeting copilot that joins Zoom and Google Meet as itself, transcribes Urdu and English live,
          extracts decisions, and assigns action items to the person actually responsible — with deadlines
          that notify them automatically.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
          <Link href="/login" className="btn btn-primary btn-lg"><Icon name="logIn" size={16} /> Open workspace</Link>
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16, marginBottom: 60 }}>
        {FEATURES.map((f) => (
          <div key={f.title} className="glass-panel">
            <div style={{ width: 36, height: 36, borderRadius: "var(--radius-sm)", background: "var(--accent-primary-tint)", color: "var(--accent-primary)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 14 }}>
              <Icon name={f.icon} size={17} />
            </div>
            <h3 style={{ fontSize: 15.5, marginBottom: 8 }}>{f.title}</h3>
            <p style={{ color: "var(--text-secondary)", fontSize: 13, lineHeight: 1.6 }}>{f.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
