"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import Icon from "./Icon";
import Waveform from "./Waveform";
import { useVoiceInput } from "./useVoiceInput";

interface Exchange {
  id: string;
  question: string;
  answer: string;
  sources: Array<{ meeting_id: number; title: string }>;
  streaming?: boolean;
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
 * Chrome/Edge only, hidden elsewhere). Answers stream in as they're
 * generated — a written answer can take 20-40s on modest hardware, and a
 * blank panel for that whole time reads as broken.
 */
export default function AskAlinaPanel({ assistantName = "Alina" }: { assistantName?: string }) {
  const [question, setQuestion] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const { listening, supported: voiceSupported, toggle: toggleVoice } = useVoiceInput((finalText) => ask(finalText));
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [exchanges]);

  async function ask(text: string) {
    const q = text.trim();
    if (!q || loading) return;
    setLoading(true);
    setError("");
    setQuestion("");
    const id = String(Date.now());
    setExchanges((prev) => [...prev, { id, question: q, answer: "", sources: [], streaming: true }]);
    try {
      const result = await api.askWorkspaceStream(q, (textSoFar) => {
        setExchanges((prev) => prev.map((ex) => (ex.id === id ? { ...ex, answer: textSoFar } : ex)));
      });
      setExchanges((prev) =>
        prev.map((ex) => (ex.id === id ? { ...ex, answer: result.answer, sources: result.sources, streaming: false } : ex))
      );
    } catch (err: any) {
      setExchanges((prev) => prev.filter((ex) => ex.id !== id));
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

      {listening && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 2px", fontSize: 12.5, color: "var(--text-secondary)" }}>
          <Waveform size={16} active />
          Listening — ask your question…
        </div>
      )}

      {exchanges.length > 0 && (
        <div className="alina-thread" style={{ marginTop: listening ? 0 : 4 }}>
          {exchanges.map((ex) => (
            <div key={ex.id}>
              <div className="alina-row alina-row-q">
                <div className="alina-bubble alina-bubble-q">{ex.question}</div>
              </div>
              <div className="alina-row alina-row-a">
                <span className="alina-avatar"><Waveform size={12} active={!!ex.streaming} /></span>
                <div className="alina-bubble alina-bubble-a">
                  {ex.answer || (ex.streaming ? "" : "…")}
                  {ex.streaming && <span className="alina-cursor" />}
                  {ex.sources.length > 0 && (
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                      {ex.sources.map((s) => (
                        <Link key={s.meeting_id} href={`/meetings/${s.meeting_id}`} className="badge badge-indigo" style={{ cursor: "pointer" }}>
                          <Icon name="video" size={10} /> {s.title}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
          <div ref={endRef} />
        </div>
      )}

      <style>{`
        .alina-thread {
          display: flex; flex-direction: column; gap: 14px;
          max-height: 340px; overflow-y: auto; padding-right: 2px;
        }
        .alina-row { display: flex; margin-bottom: 6px; }
        .alina-row-q { justify-content: flex-end; }
        .alina-row-a { justify-content: flex-start; align-items: flex-start; gap: 8px; }
        .alina-avatar {
          width: 22px; height: 22px; border-radius: 50%; flex-shrink: 0;
          background: var(--accent-primary-tint); color: var(--accent-primary);
          display: flex; align-items: center; justify-content: center; margin-top: 2px;
        }
        .alina-bubble {
          max-width: 82%; padding: 9px 13px; border-radius: var(--radius-md);
          font-size: 12.5px; line-height: 1.6; white-space: pre-wrap; word-break: break-word;
        }
        .alina-bubble-q { background: var(--accent-gradient); color: var(--text-on-accent); border-bottom-right-radius: 4px; font-weight: 500; }
        .alina-bubble-a { background: var(--bg-subtle); border: 1px solid var(--border-subtle); color: var(--text-secondary); border-bottom-left-radius: 4px; }
        .alina-cursor {
          display: inline-block; width: 6px; height: 13px; margin-left: 2px;
          background: var(--accent-primary); vertical-align: text-bottom;
          animation: alina-blink 0.9s step-end infinite;
        }
        @keyframes alina-blink { 50% { opacity: 0; } }
      `}</style>
    </div>
  );
}
