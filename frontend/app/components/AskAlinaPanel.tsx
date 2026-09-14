"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
import Icon from "./Icon";
import Waveform from "./Waveform";
import { useVoiceInput } from "./useVoiceInput";

interface Exchange {
  id: string;
  question: string;
  answer: string;
  sources: Array<{ meeting_id: number; title: string }>;
}

const SUGGESTIONS = [
  "What's still open across my meetings?",
  "What did we decide this week?",
  "Who has the most overdue tasks?",
];

/**
 * A workspace-wide "ask Alina" box — grounded across every meeting the
 * viewer can see, not just one. Used on both the employee and admin
 * dashboards, so a question can be asked from wherever the person is
 * working, not only from inside a specific meeting. Takes typed or spoken
 * questions (the mic button uses the browser's own speech recognition —
 * Chrome/Edge only, hidden elsewhere).
 */
export default function AskAlinaPanel({ assistantName = "Alina" }: { assistantName?: string }) {
  const [question, setQuestion] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const { listening, supported: voiceSupported, toggle: toggleVoice } = useVoiceInput((finalText) => ask(finalText));

  async function ask(text: string) {
    const q = text.trim();
    if (!q || loading) return;
    setLoading(true);
    setError("");
    setQuestion("");
    try {
      const result = await api.askWorkspace(q);
      setExchanges((prev) => [
        { id: String(Date.now()), question: q, answer: result.answer, sources: result.sources },
        ...prev,
      ]);
    } catch (err: any) {
      setError(err?.message || `${assistantName} couldn't answer that right now.`);
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    ask(question);
  }

  return (
    <div className="glass-panel" style={{ position: "relative", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
        <div style={{ width: 36, height: 36, borderRadius: "var(--radius-sm)", background: "var(--accent-primary-tint)", color: "var(--accent-primary)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <Waveform size={18} active={loading || listening} />
        </div>
        <div>
          <h2 style={{ fontSize: 15 }}>Ask {assistantName}</h2>
          <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>Grounded across every meeting you can see</span>
        </div>
      </div>

      {error && <div className="alert-box alert-error" style={{ marginBottom: 12 }}><Icon name="alert" size={14} />{error}</div>}

      <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <div style={{ position: "relative", flex: 1 }}>
          <input
            type="text"
            className="form-input"
            placeholder={listening ? "Listening…" : `Ask ${assistantName} anything about your meetings…`}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={loading}
            style={{ paddingRight: voiceSupported ? 40 : undefined }}
          />
          {voiceSupported && (
            <button
              type="button"
              onClick={() => toggleVoice(setQuestion)}
              disabled={loading}
              title={listening ? "Stop listening" : "Ask by voice"}
              style={{
                position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)",
                width: 26, height: 26, borderRadius: "var(--radius-full)", border: "none",
                background: listening ? "var(--accent-rose)" : "transparent",
                color: listening ? "var(--text-on-accent)" : "var(--text-muted)",
                cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
              }}
            >
              <Icon name="mic" size={13} />
            </button>
          )}
        </div>
        <button type="submit" className="btn btn-primary" disabled={loading || !question.trim()} style={{ flexShrink: 0 }}>
          {loading ? <span className="spinner" /> : <Icon name="send" size={14} />}
        </button>
      </form>

      {exchanges.length === 0 && !loading && !listening && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" onClick={() => ask(s)} className="btn btn-ghost btn-sm" style={{ border: "1px solid var(--border-card)" }}>
              {s}
            </button>
          ))}
        </div>
      )}

      {(loading || listening) && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 2px", fontSize: 12.5, color: "var(--text-secondary)" }}>
          <Waveform size={16} active />
          {listening ? "Listening — ask your question…" : "Thinking through your meetings…"}
        </div>
      )}

      {exchanges.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12, maxHeight: 320, overflowY: "auto", marginTop: loading || listening ? 0 : 4 }}>
          {exchanges.map((ex) => (
            <div key={ex.id} style={{ background: "var(--bg-subtle)", borderRadius: "var(--radius-md)", padding: 13, border: "1px solid var(--border-subtle)" }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-primary)", marginBottom: 6, display: "flex", gap: 7 }}>
                <span style={{ marginTop: 2, flexShrink: 0 }}><Icon name="message" size={13} /></span>
                {ex.question}
              </div>
              <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.6, marginBottom: ex.sources.length ? 8 : 0, whiteSpace: "pre-wrap" }}>{ex.answer}</p>
              {ex.sources.length > 0 && (
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {ex.sources.map((s) => (
                    <Link key={s.meeting_id} href={`/meetings/${s.meeting_id}`} className="badge badge-indigo" style={{ cursor: "pointer" }}>
                      <Icon name="video" size={10} /> {s.title}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
