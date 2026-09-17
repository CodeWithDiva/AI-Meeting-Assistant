"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, authStorage, Conversation, DirectMessage, TeamMember, User } from "@/lib/api";
import { displayName, initials, relativeTime } from "@/lib/format";
import Icon from "@/app/components/Icon";

export default function MessagesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [me, setMe] = useState<User | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [activeUser, setActiveUser] = useState<TeamMember | null>(null);
  const [thread, setThread] = useState<DirectMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loadingList, setLoadingList] = useState(true);
  const [loadingThread, setLoadingThread] = useState(false);
  const [sending, setSending] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [error, setError] = useState("");

  const wsRef = useRef<WebSocket | null>(null);
  const threadEndRef = useRef<HTMLDivElement>(null);
  const activeUserRef = useRef<TeamMember | null>(null);
  activeUserRef.current = activeUser;

  const openThreadWith = useCallback(async (user: TeamMember) => {
    setActiveUser(user);
    setShowPicker(false);
    setLoadingThread(true);
    try {
      const msgs = await api.getMessageThread(user.id);
      setThread(msgs);
      setConversations((prev) =>
        prev.map((c) => (c.user.id === user.id ? { ...c, unread_count: 0 } : c))
      );
    } catch (e: any) {
      setError(e.message || "Failed to load conversation.");
    } finally {
      setLoadingThread(false);
    }
  }, []);

  useEffect(() => {
    if (!authStorage.isLoggedIn()) {
      router.push("/login");
      return;
    }
    (async () => {
      try {
        const [meRes, convos, team] = await Promise.all([
          api.getMe(),
          api.getConversations(),
          api.getTeamMembers(),
        ]);
        setMe(meRes);
        setConversations(convos);
        setMembers(team.filter((m) => m.id !== meRes.id));

        const toId = searchParams.get("to");
        if (toId) {
          const target =
            team.find((m) => String(m.id) === toId) ||
            convos.find((c) => String(c.user.id) === toId)?.user;
          if (target) await openThreadWith(target);
        }
      } catch (e: any) {
        setError(e.message || "Failed to load messages.");
      } finally {
        setLoadingList(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  useEffect(() => {
    if (!me) return;
    const ws = new WebSocket(api.getMessagesWebSocketUrl());
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const { event: type, data } = JSON.parse(event.data);
        if (type !== "new_message") return;
        const msg: DirectMessage = data;
        const counterpartId = msg.sender_id === me.id ? msg.recipient_id : msg.sender_id;
        const active = activeUserRef.current;

        if (active && active.id === counterpartId) {
          setThread((prev) => (prev.some((m) => m.id === msg.id) ? prev : [...prev, msg]));
        }

        setConversations((prev) => {
          const existing = prev.find((c) => c.user.id === counterpartId);
          const isUnread = msg.recipient_id === me.id && !(active && active.id === counterpartId);
          if (existing) {
            return prev
              .map((c) =>
                c.user.id === counterpartId
                  ? { ...c, last_message: msg, unread_count: isUnread ? c.unread_count + 1 : c.unread_count }
                  : c
              )
              .sort((a, b) => (b.last_message?.created_at || "").localeCompare(a.last_message?.created_at || ""));
          }
          const counterpart = members.find((m) => m.id === counterpartId);
          if (!counterpart) return prev;
          return [{ user: counterpart, last_message: msg, unread_count: isUnread ? 1 : 0 }, ...prev];
        });
      } catch {
        // ignore malformed frames
      }
    };

    return () => ws.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me, members]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [thread]);

  async function handleSend() {
    const text = draft.trim();
    if (!text || !activeUser || sending) return;
    setSending(true);
    setDraft("");
    try {
      const msg = await api.sendDirectMessage(activeUser.id, text);
      // The DM websocket echoes this same message back to the sender too (so
      // other open tabs stay in sync) — it can land before this response
      // does, so guard against adding it twice.
      setThread((prev) => (prev.some((m) => m.id === msg.id) ? prev : [...prev, msg]));
      setConversations((prev) => {
        const existing = prev.find((c) => c.user.id === activeUser.id);
        const next = existing
          ? prev.map((c) => (c.user.id === activeUser.id ? { ...c, last_message: msg } : c))
          : [{ user: activeUser, last_message: msg, unread_count: 0 }, ...prev];
        return next.sort((a, b) => (b.last_message?.created_at || "").localeCompare(a.last_message?.created_at || ""));
      });
    } catch (e: any) {
      setError(e.message || "Failed to send message.");
      setDraft(text);
    } finally {
      setSending(false);
    }
  }

  const pickerResults = members.filter((m) => {
    const q = pickerQuery.trim().toLowerCase();
    if (!q) return true;
    return displayName(m).toLowerCase().includes(q) || m.email.toLowerCase().includes(q);
  });

  return (
    <div className="app-container" style={{ paddingBottom: 24 }}>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: 22, marginBottom: 4 }}>Messages</h1>
        <p style={{ color: "var(--text-secondary)", fontSize: 13.5 }}>
          Message anyone in the workspace directly — no need to wait for a meeting.
        </p>
      </div>

      {error && (
        <div className="alert-box alert-error">
          <Icon name="alert" size={16} />
          <span>{error}</span>
        </div>
      )}

      <div className="messages-shell">
        <aside className="messages-list glass-panel">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <span style={{ fontSize: 12.5, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
              Conversations
            </span>
            <button type="button" className="icon-btn" title="New message" onClick={() => setShowPicker((v) => !v)}>
              <Icon name="plus" size={15} />
            </button>
          </div>

          {showPicker && (
            <div className="message-picker dropdown-pop">
              <input
                autoFocus
                className="form-input"
                placeholder="Search people…"
                value={pickerQuery}
                onChange={(e) => setPickerQuery(e.target.value)}
                style={{ marginBottom: 8 }}
              />
              <div style={{ maxHeight: 220, overflowY: "auto", display: "flex", flexDirection: "column", gap: 2 }}>
                {pickerResults.length === 0 && (
                  <div style={{ fontSize: 12.5, color: "var(--text-muted)", padding: "8px 4px" }}>No one matches.</div>
                )}
                {pickerResults.map((m) => (
                  <button key={m.id} className="conversation-row" onClick={() => openThreadWith(m)}>
                    <span className="avatar" style={{ width: 28, height: 28, fontSize: 11 }}>{initials(displayName(m))}</span>
                    <span style={{ overflow: "hidden" }}>
                      <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {displayName(m)}
                      </div>
                      <div style={{ fontSize: 11.5, color: "var(--text-dim)" }}>{m.role === "admin" ? "Admin" : "Employee"}</div>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {!showPicker && (
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {loadingList && <div style={{ fontSize: 12.5, color: "var(--text-muted)", padding: "8px 4px" }}>Loading…</div>}
              {!loadingList && conversations.length === 0 && (
                <div className="empty-state" style={{ padding: "36px 10px" }}>
                  <div className="icon-wrap"><Icon name="message" size={18} /></div>
                  <h4>No conversations yet</h4>
                  <p>Tap + to message someone in your workspace.</p>
                </div>
              )}
              {conversations.map((c) => (
                <button
                  key={c.user.id}
                  className={`conversation-row ${activeUser?.id === c.user.id ? "is-active" : ""}`}
                  onClick={() => openThreadWith(c.user)}
                >
                  <span className="avatar" style={{ width: 34, height: 34, fontSize: 12.5 }}>{initials(displayName(c.user))}</span>
                  <span style={{ overflow: "hidden", flex: 1 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
                      <span style={{ fontSize: 13.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {displayName(c.user)}
                      </span>
                      {c.last_message && (
                        <span style={{ fontSize: 10.5, color: "var(--text-dim)", flexShrink: 0 }}>
                          {relativeTime(c.last_message.created_at)}
                        </span>
                      )}
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
                      <span style={{ fontSize: 12, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {c.last_message?.body || "No messages yet"}
                      </span>
                      {c.unread_count > 0 && (
                        <span className="badge badge-amber" style={{ flexShrink: 0 }}>{c.unread_count}</span>
                      )}
                    </div>
                  </span>
                </button>
              ))}
            </div>
          )}
        </aside>

        <section className="messages-thread glass-panel">
          {!activeUser ? (
            <div className="empty-state" style={{ margin: "auto" }}>
              <div className="icon-wrap"><Icon name="message" size={18} /></div>
              <h4>Select a conversation</h4>
              <p>Or start a new one from the list on the left.</p>
            </div>
          ) : (
            <>
              <div className="thread-header">
                <span className="avatar" style={{ width: 32, height: 32, fontSize: 12 }}>{initials(displayName(activeUser))}</span>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>{displayName(activeUser)}</div>
                  <div style={{ fontSize: 11.5, color: "var(--text-dim)" }}>{activeUser.role === "admin" ? "Admin" : "Employee"} · {activeUser.email}</div>
                </div>
              </div>

              <div className="thread-body">
                {loadingThread && <div style={{ textAlign: "center", color: "var(--text-muted)", fontSize: 13, padding: 20 }}>Loading…</div>}
                {!loadingThread && thread.length === 0 && (
                  <div style={{ textAlign: "center", color: "var(--text-muted)", fontSize: 13, padding: 20 }}>
                    Say hello to start the conversation.
                  </div>
                )}
                {thread.map((m) => {
                  const mine = me && m.sender_id === me.id;
                  return (
                    <div key={m.id} className={`bubble-row ${mine ? "mine" : ""}`}>
                      <div className={`bubble ${mine ? "bubble-mine" : "bubble-theirs"}`}>
                        {m.body}
                        <div className="bubble-time">{relativeTime(m.created_at)}</div>
                      </div>
                    </div>
                  );
                })}
                <div ref={threadEndRef} />
              </div>

              <div className="thread-composer">
                <input
                  className="form-input"
                  placeholder={`Message ${displayName(activeUser)}…`}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                />
                <button type="button" className="btn btn-primary" disabled={!draft.trim() || sending} onClick={handleSend}>
                  <Icon name="send" size={14} />
                  Send
                </button>
              </div>
            </>
          )}
        </section>
      </div>

      <style>{`
        .messages-shell {
          display: grid;
          grid-template-columns: 300px 1fr;
          gap: 16px;
          align-items: stretch;
          min-height: 560px;
        }
        .messages-list { display: flex; flex-direction: column; padding: 16px; overflow: hidden; }
        .messages-thread { display: flex; flex-direction: column; padding: 0; overflow: hidden; }
        .conversation-row {
          display: flex; align-items: center; gap: 10px; width: 100%;
          text-align: left; background: none; border: none; cursor: pointer;
          padding: 9px 8px; border-radius: var(--radius-sm);
          color: var(--text-primary);
          transition: background 0.15s ease;
        }
        .conversation-row:hover { background: var(--bg-subtle); }
        .conversation-row.is-active { background: var(--accent-primary-tint); }
        .message-picker { display: flex; flex-direction: column; }
        .thread-header {
          display: flex; align-items: center; gap: 10px;
          padding: 16px 20px; border-bottom: 1px solid var(--border-subtle);
        }
        .thread-body {
          flex: 1; overflow-y: auto; padding: 18px 20px;
          display: flex; flex-direction: column; gap: 8px;
        }
        .bubble-row { display: flex; }
        .bubble-row.mine { justify-content: flex-end; }
        .bubble {
          max-width: 66%; padding: 9px 13px; border-radius: var(--radius-md);
          font-size: 13.5px; line-height: 1.45; white-space: pre-wrap; word-break: break-word;
        }
        .bubble-theirs { background: var(--bg-subtle); color: var(--text-primary); border-bottom-left-radius: 4px; }
        .bubble-mine { background: var(--accent-gradient); color: var(--text-on-accent); border-bottom-right-radius: 4px; }
        .bubble-time { font-size: 10px; opacity: 0.65; margin-top: 4px; }
        .thread-composer {
          display: flex; gap: 10px; padding: 14px 20px;
          border-top: 1px solid var(--border-subtle);
        }
        .thread-composer .form-input { flex: 1; }
        @media (max-width: 760px) {
          .messages-shell { grid-template-columns: 1fr; }
          .messages-thread { min-height: 420px; }
        }
      `}</style>
    </div>
  );
}
