"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import LiveRecorder from "@/app/components/LiveRecorder";
import Icon from "@/app/components/Icon";
import Waveform from "@/app/components/Waveform";
import { useVoiceInput } from "@/app/components/useVoiceInput";
import {
  ActionItem,
  AgentState,
  api,
  authStorage,
  Decision,
  MeetingDetail,
  MeetingInsights,
  Recording,
  Segment,
  Speaker,
  SystemCapabilities,
  TaskPriority,
  TeamMember,
} from "@/lib/api";
import { dueInfo, formatDateTime, toLocalInput } from "@/lib/format";

export default function MeetingDetailPage() {
  const params = useParams();
  const router = useRouter();
  const meetingId = Number(params.id);

  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [caps, setCaps] = useState<SystemCapabilities | null>(null);
  const [activeTab, setActiveTab] = useState<"summary" | "decisions" | "tasks" | "transcript" | "chat" | "agent" | "insights">("summary");
  const [insights, setInsights] = useState<MeetingInsights | null>(null);

  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [transcriptSearch, setTranscriptSearch] = useState("");

  // Action items inline form
  const [newTaskText, setNewTaskText] = useState("");
  const [newTaskAssigneeId, setNewTaskAssigneeId] = useState("");
  const [newTaskDeadline, setNewTaskDeadline] = useState("");
  const [newTaskPriority, setNewTaskPriority] = useState<TaskPriority>("medium");
  const [addingTask, setAddingTask] = useState(false);

  // Speaker editing state
  const [editingSpeakerId, setEditingSpeakerId] = useState<number | null>(null);
  const [editSpeakerName, setEditSpeakerName] = useState("");
  const [updatingSpeaker, setUpdatingSpeaker] = useState(false);

  // AI Meeting Chat state + TTS
  const [chatMessages, setChatMessages] = useState<{ sender: "user" | "ai"; text: string; sources?: string[] }[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [playingTTS, setPlayingTTS] = useState(false);

  // Meeting agent
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [agentBusy, setAgentBusy] = useState(false);
  const [meetingLink, setMeetingLink] = useState("");
  const [recordAudio, setRecordAudio] = useState(false);
  const [agentSimulated, setAgentSimulated] = useState(false);
  const [agentParticipants, setAgentParticipants] = useState<string[]>([]);
  const [activeSpeaker, setActiveSpeaker] = useState<string | null>(null);
  const [micCaptured, setMicCaptured] = useState<boolean | null>(null);
  const [currentUserRole, setCurrentUserRole] = useState<string>("");

  // Assistant voice reply + realtime WS
  const [wsConnected, setWsConnected] = useState(false);
  const [assistantReplies, setAssistantReplies] = useState<
    { id: string; question: string; answer: string; audio_base64: string; timestamp: string }[]
  >([]);
  const [liveTranscripts, setLiveTranscripts] = useState<{ speaker: string; text: string; timestamp: string }[]>([]);
  const [assistantTestInput, setAssistantTestInput] = useState("");
  const { listening: testListening, supported: voiceSupported, toggle: toggleTestVoice } = useVoiceInput(
    (finalText) => handleTestAssistantReply(undefined, finalText)
  );
  const [testingAssistant, setTestingAssistant] = useState(false);

  const agentIsActive = agentState === "JOINING" || agentState === "IN_MEETING";
  const assistantName = caps?.assistant_name || "Alina";
  const wakeWord = caps?.wake_word || assistantName.split(" ")[0];

  useEffect(() => {
    if (!authStorage.isLoggedIn()) {
      router.push("/login");
      return;
    }
    if (isNaN(meetingId)) {
      setLoading(false);
      setError("Invalid meeting ID in the URL. Pick a meeting from Dashboard or Meetings.");
      return;
    }
    if (meetingId) loadMeetingData();
    api.getSystemCapabilities().then(setCaps).catch(() => undefined);
    api.getTeamMembers().then(setMembers).catch(() => setMembers([]));
  }, [meetingId, router]);

  useEffect(() => {
    if (!authStorage.isLoggedIn()) return;
    api.getMe().then((user) => setCurrentUserRole(user.role || "employee")).catch(() => undefined);
    const refreshAgentStatus = () => {
      api.getAgentStatus(meetingId).then((status) => {
        setAgentState(status.state || "idle");
        setAgentSimulated(status.simulated);
        setAgentParticipants(status.participants || []);
        setActiveSpeaker(status.active_speaker || null);
        setMicCaptured(status.mic_captured ?? null);
      }).catch(() => undefined);
    };
    refreshAgentStatus();
    const interval = window.setInterval(refreshAgentStatus, 3000);
    return () => window.clearInterval(interval);
  }, [meetingId]);

  useEffect(() => {
    if (!meetingId || typeof window === "undefined") return;
    const wsUrl = api.getMeetingWebSocketUrl(meetingId);
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(wsUrl);
      ws.onopen = () => setWsConnected(true);
      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          const payload = message.data ?? {};
          if (message.event === "agent_state") {
            setAgentState(payload.state || "idle");
            if (typeof payload.simulated === "boolean") setAgentSimulated(payload.simulated);
            if (typeof payload.mic_captured === "boolean") setMicCaptured(payload.mic_captured);
            if (payload.error) setError(payload.error);
            else if (payload.message) setSuccess(payload.message);
          } else if (message.event === "notice") {
            // A heads-up from the assistant that isn't a state change, e.g.
            // "your PC is nearly out of memory — transcription will be less accurate".
            if (payload.message) setError(payload.message);
          } else if (message.event === "notes_ready") {
            loadMeetingData();
          } else if (message.event === "ava_reply") {
            if (payload.audio_base64) {
              try { new Audio(`data:audio/wav;base64,${payload.audio_base64}`).play().catch(() => {}); } catch {}
            }
            setAssistantReplies((prev) => [
              { id: String(Date.now()), question: payload.question || "", answer: payload.answer || "", audio_base64: payload.audio_base64 || "", timestamp: new Date().toLocaleTimeString() },
              ...prev,
            ]);
          } else if (message.event === "transcript_live") {
            setLiveTranscripts((prev) => [...prev, { speaker: payload.speaker || "Speaker", text: payload.text || "", timestamp: new Date().toLocaleTimeString() }]);
          }
        } catch {}
      };
      ws.onclose = () => setWsConnected(false);
      ws.onerror = () => setWsConnected(false);
    } catch {
      setWsConnected(false);
    }
    return () => { ws?.close(); };
  }, [meetingId]);

  async function handleTestAssistantReply(e?: FormEvent, overrideText?: string) {
    e?.preventDefault();
    const raw = (overrideText ?? assistantTestInput).trim();
    if (!raw || testingAssistant) return;

    let inputText = raw;
    if (!inputText.toLowerCase().includes(wakeWord.toLowerCase())) {
      inputText = `${assistantName}, ${inputText}`;
    }

    setTestingAssistant(true);
    setError("");
    try {
      const result = await api.testVoiceReply(meetingId, inputText);
      if (!result.triggered) {
        setError(result.message || `Wake word "${assistantName}" not detected. Start with "${assistantName}, ..."`);
        return;
      }
      if (result.audio_base64) {
        try { new Audio(`data:audio/wav;base64,${result.audio_base64}`).play().catch(() => {}); } catch {}
      }
      setAssistantReplies((prev) => [
        { id: String(Date.now()), question: result.question || inputText, answer: result.answer || "No answer generated.", audio_base64: result.audio_base64 || "", timestamp: new Date().toLocaleTimeString() },
        ...prev,
      ]);
      setAssistantTestInput("");
    } catch (err: any) {
      setError(err?.message || `Could not get a reply from ${assistantName}. Is the backend and Ollama running?`);
    } finally {
      setTestingAssistant(false);
    }
  }

  async function loadMeetingData() {
    setLoading(true);
    setError("");
    try {
      const [detail, recData, speakersData, agentData] = await Promise.all([
        api.getMeeting(meetingId),
        api.getRecording(meetingId).catch(() => null),
        api.getSpeakers(meetingId).catch(() => []),
        api.getAgentStatus(meetingId).catch(() => null),
      ]);

      setMeeting(detail);
      setInsights(await api.getMeetingInsights(meetingId).catch(() => null));
      setRecording(recData);
      setSpeakers(speakersData);
      if (agentData) {
        setAgentState(agentData.state || "idle");
        setAgentSimulated(agentData.simulated);
        setAgentParticipants(agentData.participants || []);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to load meeting details");
    } finally {
      setLoading(false);
    }
  }

  async function handleAudioUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError("");
    setSuccess("");
    try {
      const result = await api.uploadAudio(meetingId, file);
      setSuccess(`Audio transcribed (${result.segment_count || 0} segments extracted).`);
      const [detail, speakersData] = await Promise.all([api.getMeeting(meetingId), api.getSpeakers(meetingId)]);
      setMeeting(detail);
      setSpeakers(speakersData);
      setActiveTab("transcript");
    } catch (err: any) {
      setError(err?.message || "Failed to upload or transcribe audio.");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  async function handleAnalyze() {
    if (!meeting?.transcript) {
      setError("Upload an audio file or record live speech first.");
      return;
    }
    setAnalyzing(true);
    setError("");
    setSuccess("");
    try {
      await api.analyzeMeeting(meetingId);
      setSuccess("Analysis complete — summary, decisions and action items updated.");
      setMeeting(await api.getMeeting(meetingId));
      setActiveTab("summary");
    } catch (err: any) {
      setError(err?.message || "AI analysis failed.");
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleExport() {
    if (!meeting) return;
    setExporting(true);
    try {
      await api.exportMeeting(meetingId, meeting.title);
    } catch (err: any) {
      setError(err?.message || "Could not export this meeting.");
    } finally {
      setExporting(false);
    }
  }

  async function handleToggleRecording() {
    if (!recording) return;
    const newEnabled = !recording.enabled;
    try {
      const updated = await api.toggleRecording(meetingId, newEnabled);
      setRecording(updated);
      setSuccess(newEnabled ? "Recording enabled with consent tracking." : "Recording disabled (transcript only).");
    } catch (err: any) {
      setError(err?.message || "Failed to update recording settings");
    }
  }

  async function handleRenameSpeaker(speakerId: number) {
    if (!editSpeakerName.trim()) { setEditingSpeakerId(null); return; }
    setUpdatingSpeaker(true);
    try {
      const updated = await api.updateSpeakerName(meetingId, speakerId, editSpeakerName.trim());
      setSpeakers(speakers.map((s) => (s.id === speakerId ? updated : s)));
      setEditingSpeakerId(null);
      setEditSpeakerName("");
      setSuccess(`Speaker identified as "${updated.display_name}".`);
    } catch (err: any) {
      setError(err?.message || "Failed to rename speaker");
    } finally {
      setUpdatingSpeaker(false);
    }
  }

  async function handleSendChatMessage(overrideText?: string) {
    const textToSend = overrideText || chatInput;
    if (!textToSend.trim()) return;
    const userMsg = textToSend.trim();
    setChatMessages((prev) => [...prev, { sender: "user", text: userMsg }]);
    if (!overrideText) setChatInput("");
    setChatLoading(true);
    try {
      const response = await api.askMeetingQuestion(meetingId, userMsg);
      setChatMessages((prev) => [...prev, { sender: "ai", text: response.answer, sources: response.sources }]);
    } catch {
      setChatMessages((prev) => [...prev, { sender: "ai", text: "I couldn't retrieve an answer from the transcript. Please try again." }]);
    } finally {
      setChatLoading(false);
    }
  }

  async function handleSpeakText(text: string) {
    if (playingTTS) return;
    setPlayingTTS(true);
    try {
      if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.0;
        utterance.onend = () => setPlayingTTS(false);
        utterance.onerror = () => setPlayingTTS(false);
        window.speechSynthesis.speak(utterance);
        return;
      }
      const res = await api.speakText(meetingId, text);
      if (res.audio_base64) {
        const audio = new Audio(`data:${res.content_type};base64,${res.audio_base64}`);
        audio.onended = () => setPlayingTTS(false);
        audio.onerror = () => setPlayingTTS(false);
        audio.play();
      } else {
        setPlayingTTS(false);
      }
    } catch {
      setPlayingTTS(false);
    }
  }

  function handleLiveSegment(newSeg: Segment) {
    if (!meeting) return;
    setMeeting({ ...meeting, segments: [...(meeting.segments || []), newSeg], transcript: `${meeting.transcript || ""} ${newSeg.text}`.trim() });
  }

  function handleLiveActionCreated(taskText: string) {
    setSuccess(`Auto-detected live action item: "${taskText}"`);
    loadMeetingData();
  }

  async function handleToggleTaskStatus(taskId: number, currentStatus: string) {
    const nextStatus = currentStatus === "done" ? "pending" : "done";
    try {
      const updatedItem = await api.updateTask(taskId, { status: nextStatus });
      if (meeting) setMeeting({ ...meeting, action_items: meeting.action_items.map((item) => (item.id === taskId ? updatedItem : item)) });
    } catch (err: any) {
      setError(err?.message || "Failed to update task");
    }
  }

  async function handleDeleteTask(taskId: number) {
    try {
      await api.deleteTask(taskId);
      if (meeting) setMeeting({ ...meeting, action_items: meeting.action_items.filter((item) => item.id !== taskId) });
    } catch (err: any) {
      setError(err?.message || "Failed to delete task");
    }
  }

  async function handleCreateTask(e: FormEvent) {
    e.preventDefault();
    if (!newTaskText.trim()) return;
    setAddingTask(true);
    try {
      const created = await api.createTask(meetingId, {
        task: newTaskText.trim(),
        assignee_user_id: newTaskAssigneeId ? Number(newTaskAssigneeId) : undefined,
        deadline: newTaskDeadline.trim() || undefined,
        priority: newTaskPriority,
      });
      if (meeting) setMeeting({ ...meeting, action_items: [created, ...(meeting.action_items || [])] });
      setNewTaskText(""); setNewTaskAssigneeId(""); setNewTaskDeadline(""); setNewTaskPriority("medium");
      setSuccess(`Task assigned to ${created.assignee || "no one yet"}.`);
    } catch (err: any) {
      setError(err?.message || "Failed to create task");
    } finally {
      setAddingTask(false);
    }
  }

  async function handleAgentToggle() {
    if (agentIsActive) {
      setAgentBusy(true);
      setError("");
      try {
        const result = await api.leaveMeeting(meetingId);
        setAgentState("COMPLETE");
        const { decisions = 0, action_items = 0, assigned = 0 } = result.notes || {};
        setSuccess(`${result.message} ${decisions} decision(s) and ${action_items} task(s) extracted, ${assigned} assigned automatically.`);
        await loadMeetingData();
      } catch (err: any) {
        setError(err?.message || "Could not disconnect the assistant.");
      } finally {
        setAgentBusy(false);
      }
      return;
    }

    if (!meetingLink.trim()) {
      setError("Pehle Zoom ya Google Meet ka link paste karein.");
      return;
    }
    setAgentBusy(true);
    setError("");
    try {
      const result = await api.joinExistingMeeting(meetingId, meetingLink.trim(), recordAudio);
      setAgentState("JOINING");
      setSuccess(result.message);
    } catch (err: any) {
      setError(err?.message || "Assistant meeting join nahi kar saka. Dobara try karein.");
      setAgentState("FAILED_JOIN");
    } finally {
      setAgentBusy(false);
    }
  }

  function getSpeakerDisplayName(rawLabel: string | null | undefined): string {
    if (!rawLabel) return "Speaker";
    const found = speakers.find((s) => s.speaker_label === rawLabel);
    return found?.display_name || rawLabel;
  }

  function formatTime(seconds: number) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  }

  function formatSummary(text: string) {
    return text.split(/\n+|(?<=[.!?])\s+(?=[A-Z])/).map((line) => line.replace(/^[-•*]\s*/, "").trim()).filter(Boolean);
  }

  function getAgentPillClass(state: string) {
    if (state === "IN_MEETING") return "is-live";
    if (state === "JOINING" || state === "PROCESSING") return "is-work";
    if (state === "FAILED_JOIN" || state === "DISCONNECTED") return "is-fail";
    return "is-idle";
  }

  function getAgentPresentation(state: string) {
    const states: Record<string, string> = {
      idle: "Not in a meeting",
      SCHEDULED: "Scheduled",
      JOINING: "Joining…",
      IN_MEETING: "In meeting & listening",
      PROCESSING: "Writing the notes",
      COMPLETE: "Notes ready",
      DISCONNECTED: "Disconnected",
      FAILED_JOIN: "Could not join — retry",
    };
    return states[state] || state.replaceAll("_", " ");
  }

  if (loading) {
    return (
      <div className="app-container" style={{ textAlign: "center", padding: "120px 0" }}>
        <div className="spinner" style={{ margin: "0 auto 16px", width: 22, height: 22, borderTopColor: "var(--accent-primary)", borderColor: "var(--border-card)" }} />
        <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>Loading meeting workspace…</p>
      </div>
    );
  }

  if (!meeting) {
    return (
      <div className="app-container empty-state">
        <div className="icon-wrap"><Icon name="video" size={20} /></div>
        <h4>Meeting not found</h4>
        <Link href="/meetings" className="btn btn-primary btn-sm">Back to meetings</Link>
      </div>
    );
  }

  const filteredSegments = (meeting.segments || []).filter((s) => s.text.toLowerCase().includes(transcriptSearch.toLowerCase()));
  const platform = (meeting.platform || "").toLowerCase();
  const platformLabel = platform.includes("zoom") ? "Zoom" : platform.includes("meet") ? "Google Meet" : platform === "attach" ? "Your device" : "Direct audio";

  return (
    <div className="app-container">
      <div style={{ marginBottom: 16 }}>
        <Link href="/meetings" style={{ fontSize: 13, color: "var(--text-secondary)", display: "inline-flex", alignItems: "center", gap: 6, fontWeight: 500 }}>
          <Icon name="arrowLeft" size={14} /> Back to meetings
        </Link>
      </div>

      <div className="glass-panel" style={{ marginBottom: 20, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 18, borderLeft: "3px solid var(--accent-primary)" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
            <h1 style={{ fontSize: 20 }}>{meeting.title}</h1>
            <span className="badge badge-cyan">{platformLabel}</span>
            {meeting.transcript && <span className="badge badge-emerald">Transcribed</span>}
          </div>
          <p style={{ color: "var(--text-muted)", fontSize: 12.5 }}>#{meeting.id} · Created {formatDateTime(meeting.created_at)}</p>
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button onClick={handleToggleRecording} className={`btn btn-sm ${recording?.enabled ? "btn-danger" : "btn-secondary"}`} title="Recording consent toggle">
            <span className={`status-dot ${recording?.enabled ? "status-dot-recording" : ""}`} /> {recording?.enabled ? "Recording: on" : "Record: off"}
          </button>
          <label className="btn btn-secondary btn-sm" style={{ cursor: uploading ? "wait" : "pointer" }}>
            {uploading ? <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span className="spinner" style={{ borderTopColor: "var(--text-secondary)", borderColor: "var(--border-card)" }} /> Transcribing…</span> : <><Icon name="upload" size={13} /> Upload audio</>}
            <input type="file" accept="audio/*" hidden disabled={uploading} onChange={handleAudioUpload} />
          </label>
          <button onClick={handleExport} className="btn btn-secondary btn-sm" disabled={exporting}>
            {exporting ? <span className="spinner" style={{ borderTopColor: "var(--text-secondary)", borderColor: "var(--border-card)" }} /> : <Icon name="download" size={13} />} Export
          </button>
          <button onClick={handleAnalyze} className="btn btn-primary btn-sm" disabled={analyzing || !meeting.transcript}>
            {analyzing ? <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span className="spinner" /> Analyzing…</span> : <><Icon name="layers" size={13} /> Generate notes</>}
          </button>
        </div>
      </div>

      <LiveRecorder meetingId={meetingId} onNewSegment={handleLiveSegment} onLiveActionCreated={handleLiveActionCreated} />

      {error && <div className="alert-box alert-error"><Icon name="alert" size={16} />{error}</div>}
      {success && <div className="alert-box alert-success"><Icon name="check" size={16} />{success}</div>}

      <div className="tabs-nav">
        <button className={`tab-btn ${activeTab === "summary" ? "active" : ""}`} onClick={() => setActiveTab("summary")}><Icon name="fileText" size={14} /> Summary</button>
        {currentUserRole === "admin" && (
          <button className={`tab-btn ${activeTab === "insights" ? "active" : ""}`} onClick={() => setActiveTab("insights")}><Icon name="chart" size={14} /> Insights</button>
        )}
        <button className={`tab-btn ${activeTab === "decisions" ? "active" : ""}`} onClick={() => setActiveTab("decisions")}><Icon name="flag" size={14} /> Decisions ({meeting.decisions?.length || 0})</button>
        <button className={`tab-btn ${activeTab === "tasks" ? "active" : ""}`} onClick={() => setActiveTab("tasks")}><Icon name="checkSquare" size={14} /> Tasks ({meeting.action_items?.length || 0})</button>
        <button className={`tab-btn ${activeTab === "transcript" ? "active" : ""}`} onClick={() => setActiveTab("transcript")}><Icon name="mic" size={14} /> Transcript ({meeting.segments?.length || (meeting.transcript ? 1 : 0)})</button>
        <button className={`tab-btn ${activeTab === "chat" ? "active" : ""}`} onClick={() => setActiveTab("chat")}><Icon name="message" size={14} /> Copilot</button>
        <button className={`tab-btn ${activeTab === "agent" ? "active" : ""}`} onClick={() => setActiveTab("agent")}><Icon name="radio" size={14} /> Assistant &amp; voice</button>
      </div>

      <div className="glass-panel" style={{ minHeight: 420, padding: 26 }}>
        {activeTab === "summary" && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
              <div>
                <h3 style={{ fontSize: 16, marginBottom: 4 }}>Summary &amp; highlights</h3>
                <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Synthesized from the full meeting transcript</span>
              </div>
              {meeting.summary && <span className="badge badge-purple">{meeting.summary.provider || "Local LLM"}</span>}
            </div>
            {meeting.summary?.text ? (
              <div style={{ background: "var(--bg-subtle)", padding: 22, borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
                <ul style={{ display: "grid", gap: 11, paddingLeft: 20, margin: 0, fontSize: 14, lineHeight: 1.6 }}>
                  {formatSummary(meeting.summary.text).map((point, index) => <li key={index}>{point}</li>)}
                </ul>
              </div>
            ) : (
              <div className="empty-state">
                <div className="icon-wrap"><Icon name="fileText" size={20} /></div>
                <h4>No summary generated yet</h4>
                <p>{meeting.transcript ? "Generate notes to extract a summary, decisions and tasks." : "Upload audio or use Live Mic above first."}</p>
                {meeting.transcript && <button onClick={handleAnalyze} className="btn btn-primary btn-sm" disabled={analyzing}>{analyzing ? "Synthesizing…" : "Generate notes"}</button>}
              </div>
            )}
          </div>
        )}

        {activeTab === "decisions" && (
          <div>
            <div style={{ marginBottom: 18 }}>
              <h3 style={{ fontSize: 16, marginBottom: 4 }}>Decisions</h3>
              <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Agreements and conclusions reached during the meeting</span>
            </div>
            {meeting.decisions && meeting.decisions.length > 0 ? (
              <div style={{ display: "grid", gap: 10 }}>
                {meeting.decisions.map((d, index) => (
                  <div key={d.id || index} style={{ background: "var(--bg-subtle)", padding: "14px 16px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-subtle)", display: "flex", alignItems: "flex-start", gap: 12 }}>
                    <div style={{ width: 24, height: 24, borderRadius: "50%", background: "var(--tint-emerald)", color: "var(--accent-emerald)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}><Icon name="check" size={13} /></div>
                    <p style={{ fontSize: 14, lineHeight: 1.5 }}>{d.text}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state"><div className="icon-wrap"><Icon name="flag" size={20} /></div><h4>No decisions yet</h4><p>Generate notes to extract decisions.</p></div>
            )}
          </div>
        )}

        {activeTab === "tasks" && (
          <div>
            <div style={{ marginBottom: 18 }}>
              <h3 style={{ fontSize: 16, marginBottom: 4 }}>Action items</h3>
              <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Assigned to a real team member, with a deadline and priority</span>
            </div>

            <form onSubmit={handleCreateTask} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 0.8fr auto", gap: 10, marginBottom: 22, background: "var(--bg-subtle)", padding: 15, borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
              <input type="text" className="form-input" placeholder="Task description…" value={newTaskText} onChange={(e) => setNewTaskText(e.target.value)} required />
              <select className="form-input" value={newTaskAssigneeId} onChange={(e) => setNewTaskAssigneeId(e.target.value)}>
                <option value="">Unassigned</option>
                {members.map((m) => <option key={m.id} value={m.id}>{m.full_name || m.email}</option>)}
              </select>
              <input type="text" className="form-input" placeholder="Deadline (e.g. Friday 5 PM)" value={newTaskDeadline} onChange={(e) => setNewTaskDeadline(e.target.value)} />
              <select className="form-input" value={newTaskPriority} onChange={(e) => setNewTaskPriority(e.target.value as TaskPriority)}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
              <button type="submit" className="btn btn-primary btn-sm" disabled={addingTask || !newTaskText.trim()}>{addingTask ? "Adding…" : "Assign"}</button>
            </form>

            {meeting.action_items && meeting.action_items.length > 0 ? (
              <div style={{ display: "grid", gap: 8 }}>
                {meeting.action_items.map((item) => {
                  const due = dueInfo(item);
                  return (
                    <div key={item.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 14, background: "var(--bg-subtle)", padding: "13px 16px", borderRadius: "var(--radius-sm)", border: item.status === "done" ? "1px solid var(--border-subtle)" : "1px solid var(--border-card)" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 12, flex: 1, minWidth: 0 }}>
                        <input type="checkbox" checked={item.status === "done"} onChange={() => handleToggleTaskStatus(item.id, item.status)} style={{ cursor: "pointer", accentColor: "var(--accent-primary)" }} />
                        <span className={`priority-dot priority-dot-${item.priority}`} title={`${item.priority} priority`} />
                        <div style={{ minWidth: 0 }}>
                          <p style={{ fontSize: 14, fontWeight: 500, marginBottom: 4, textDecoration: item.status === "done" ? "line-through" : "none", color: item.status === "done" ? "var(--text-muted)" : "var(--text-primary)" }}>{item.task}</p>
                          <div style={{ display: "flex", gap: 12, fontSize: 12, color: "var(--text-muted)", flexWrap: "wrap", alignItems: "center" }}>
                            {item.assignee && <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}><Icon name="user" size={11} /> {item.assignee}</span>}
                            {item.assigned_by && <span>From {item.assigned_by}</span>}
                            {(item.due_at || item.deadline) && <span className={`due-badge due-${due.tone}`}><Icon name="clock" size={11} />{due.label}</span>}
                          </div>
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                        {item.due_at && (
                          <button onClick={() => api.downloadTaskInvite(item.id, item.task).catch((e) => setError(e.message))} className="icon-btn" style={{ width: 28, height: 28 }} title="Add to calendar">
                            <Icon name="calendar" size={13} />
                          </button>
                        )}
                        <button onClick={() => handleDeleteTask(item.id)} className="icon-btn" style={{ width: 28, height: 28, color: "var(--accent-rose)" }} title="Delete task">
                          <Icon name="trash" size={13} />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="empty-state"><div className="icon-wrap"><Icon name="checkSquare" size={20} /></div><h4>No action items yet</h4></div>
            )}
          </div>
        )}

        {activeTab === "insights" && (
          <div>
            <div style={{ marginBottom: 18 }}>
              <h3 style={{ fontSize: 16, marginBottom: 4 }}>Participation insights</h3>
              <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Talk-time and engagement calculated from the timestamped transcript</span>
            </div>
            {insights?.participants.length ? (
              <div style={{ display: "grid", gap: 10 }}>
                {insights.participants.map((participant) => (
                  <div key={participant.speaker} style={{ padding: 15, background: "var(--bg-subtle)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 9 }}>
                      <strong style={{ fontSize: 13.5 }}>{getSpeakerDisplayName(participant.speaker)}</strong>
                      <span className="badge badge-cyan">{participant.engagement_score}% engaged</span>
                    </div>
                    <div className="progress-track" style={{ marginBottom: 8 }}><div className="progress-fill" style={{ width: `${participant.talk_time_percent}%` }} /></div>
                    <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text-secondary)", fontSize: 11.5 }}>
                      <span>{Math.round(participant.talk_time_seconds)}s speaking</span>
                      <span>{participant.talk_time_percent}% of talk-time</span>
                    </div>
                    <p style={{ marginTop: 9, color: "var(--text-secondary)", fontSize: 12.5 }}>{participant.coaching_tip}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state"><div className="icon-wrap"><Icon name="chart" size={20} /></div><h4>Not enough data yet</h4><p>Add a transcript with speaker timestamps.</p></div>
            )}
          </div>
        )}

        {activeTab === "transcript" && (
          <div>
            {speakers.length > 0 && (
              <div style={{ background: "var(--bg-subtle)", padding: "13px 16px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-subtle)", marginBottom: 18, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <span style={{ fontSize: 12.5, fontWeight: 700, color: "var(--text-secondary)" }}>Speakers:</span>
                {speakers.map((spk) => (
                  <div key={spk.id} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    {editingSpeakerId === spk.id ? (
                      <div style={{ display: "flex", gap: 4 }}>
                        <input type="text" className="form-input" style={{ padding: "4px 10px", fontSize: 12, width: 140 }} value={editSpeakerName} onChange={(e) => setEditSpeakerName(e.target.value)} placeholder="Speaker name…" autoFocus />
                        <button onClick={() => handleRenameSpeaker(spk.id)} className="btn btn-primary btn-sm" style={{ padding: "3px 10px", fontSize: 11 }} disabled={updatingSpeaker}>Save</button>
                        <button onClick={() => setEditingSpeakerId(null)} className="btn btn-secondary btn-sm" style={{ padding: "3px 8px", fontSize: 11 }}><Icon name="x" size={11} /></button>
                      </div>
                    ) : (
                      <button onClick={() => { setEditingSpeakerId(spk.id); setEditSpeakerName(spk.display_name || spk.speaker_label); }} className="badge badge-indigo" style={{ cursor: "pointer" }} title="Click to rename speaker">
                        <span>{spk.display_name || spk.speaker_label}</span> <Icon name="edit" size={10} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexWrap: "wrap", gap: 12 }}>
              <div>
                <h3 style={{ fontSize: 16, marginBottom: 2 }}>Transcript timeline</h3>
                <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Timestamped, speaker-attributed segments</span>
              </div>
              <div style={{ position: "relative" }}>
                <input type="text" className="form-input" placeholder="Search transcript…" style={{ width: 220, paddingLeft: 32 }} value={transcriptSearch} onChange={(e) => setTranscriptSearch(e.target.value)} />
                <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text-dim)" }}><Icon name="search" size={13} /></span>
              </div>
            </div>

            {meeting.segments && meeting.segments.length > 0 ? (
              <div style={{ display: "grid", gap: 10, maxHeight: 520, overflowY: "auto", paddingRight: 6 }}>
                {filteredSegments.map((seg, idx) => (
                  <div key={seg.id || idx} style={{ background: "var(--bg-subtle)", padding: "13px 16px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-subtle)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: "var(--text-muted)", marginBottom: 6 }}>
                      <span className="badge badge-cyan">{getSpeakerDisplayName(seg.speaker_label)}</span>
                      <span className="mono" style={{ color: "var(--text-dim)" }}>[{formatTime(seg.start_time)} – {formatTime(seg.end_time)}]</span>
                    </div>
                    <p style={{ fontSize: 13.5, lineHeight: 1.6 }}>{seg.text}</p>
                  </div>
                ))}
              </div>
            ) : meeting.transcript ? (
              <div style={{ background: "var(--bg-subtle)", padding: 18, borderRadius: "var(--radius-sm)", lineHeight: 1.7, fontSize: 13.5, whiteSpace: "pre-wrap" }}>{meeting.transcript}</div>
            ) : (
              <div className="empty-state">
                <div className="icon-wrap"><Icon name="mic" size={20} /></div>
                <h4>No transcript yet</h4>
                <label className="btn btn-primary btn-sm" style={{ cursor: "pointer" }}>
                  Upload audio<input type="file" accept="audio/*" hidden onChange={handleAudioUpload} />
                </label>
              </div>
            )}
          </div>
        )}

        {activeTab === "chat" && (
          <div>
            <div style={{ marginBottom: 16 }}>
              <h3 style={{ fontSize: 16, marginBottom: 4 }}>Meeting copilot</h3>
              <p style={{ color: "var(--text-secondary)", fontSize: 12.5 }}>Ask questions grounded in this meeting&apos;s transcript, decisions and tasks.</p>
            </div>

            <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
              <button type="button" onClick={() => handleSendChatMessage("What are the key decisions made in this meeting?")} className="btn btn-secondary btn-sm" disabled={chatLoading}><Icon name="flag" size={12} /> Key decisions?</button>
              <button type="button" onClick={() => handleSendChatMessage("Who was assigned tasks and what are their deadlines?")} className="btn btn-secondary btn-sm" disabled={chatLoading}><Icon name="checkSquare" size={12} /> Assigned tasks?</button>
              <button type="button" onClick={() => handleSendChatMessage("Summarize the main discussion points in 3 concise bullets.")} className="btn btn-secondary btn-sm" disabled={chatLoading}><Icon name="fileText" size={12} /> 3-bullet summary</button>
            </div>

            <div style={{ background: "var(--bg-subtle)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-md)", padding: 18, minHeight: 260, maxHeight: 400, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12, marginBottom: 14 }}>
              {chatMessages.length === 0 ? (
                <div style={{ textAlign: "center", padding: "44px 0", color: "var(--text-muted)", fontSize: 13 }}>Ask any question about this meeting.</div>
              ) : (
                chatMessages.map((msg, idx) => (
                  <div key={idx} style={{ alignSelf: msg.sender === "user" ? "flex-end" : "flex-start", maxWidth: "85%", background: msg.sender === "user" ? "var(--accent-primary)" : "var(--bg-surface)", color: msg.sender === "user" ? "var(--text-on-accent)" : "var(--text-primary)", padding: "11px 15px", borderRadius: "var(--radius-md)", border: msg.sender === "ai" ? "1px solid var(--border-card)" : "none", fontSize: 13.5, lineHeight: 1.6 }}>
                    <p style={{ whiteSpace: "pre-wrap" }}>{msg.text}</p>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 9, gap: 12 }}>
                      {msg.sources?.length ? <span style={{ fontSize: 10.5, opacity: 0.75 }}>{msg.sources.join(" · ")}</span> : <span />}
                      {msg.sender === "ai" && (
                        <button type="button" onClick={() => handleSpeakText(msg.text)} className="btn btn-ghost btn-sm" style={{ padding: "2px 7px" }} title="Read aloud" disabled={playingTTS}>
                          <Icon name="volume" size={12} />
                        </button>
                      )}
                    </div>
                  </div>
                ))
              )}
              {chatLoading && <div style={{ alignSelf: "flex-start", display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "var(--text-secondary)" }}><span className="spinner" style={{ borderTopColor: "var(--accent-primary)", borderColor: "var(--border-card)" }} /> Thinking…</div>}
            </div>

            <form onSubmit={(e) => { e.preventDefault(); handleSendChatMessage(); }} style={{ display: "flex", gap: 10 }}>
              <input type="text" className="form-input" placeholder="Ask about this meeting…" value={chatInput} onChange={(e) => setChatInput(e.target.value)} disabled={chatLoading} />
              <button type="submit" className="btn btn-primary" disabled={chatLoading || !chatInput.trim()}><Icon name="send" size={14} /></button>
            </form>
          </div>
        )}

        {activeTab === "agent" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
              <div>
                <h3 style={{ fontSize: 16, marginBottom: 4 }}>Meeting assistant &amp; voice</h3>
                <p style={{ color: "var(--text-secondary)", fontSize: 12.5 }}>
                  {assistantName} joins Zoom or Google Meet through its own browser, and answers out loud when you say &quot;{wakeWord}&quot;.
                </p>
              </div>
              <div className="agent-pillbar">
                <span className={`agent-pill ${wsConnected ? "is-live" : "is-idle"}`}><span className="dot" /> {wsConnected ? "Live" : "Offline"}</span>
                <span className={`agent-pill ${getAgentPillClass(agentState)}`}><span className="dot" /> {getAgentPresentation(agentState)}</span>
              </div>
            </div>

            {agentState === "IN_MEETING" && (
              <div className="alert-box alert-success" style={{ margin: 0 }}>
                <Waveform size={16} active />
                {assistantName} is listening in the meeting. Say &quot;{wakeWord}, …&quot; to get a spoken reply.
              </div>
            )}

            {agentState === "IN_MEETING" && micCaptured === false && (
              <div className="alert-box alert-warn" style={{ margin: 0 }}>
                <Icon name="alert" size={16} />
                Your microphone isn&apos;t being captured — only what plays through your speakers will be transcribed. Check <code style={{ margin: "0 4px" }}>BOT_MIC_INPUT_DEVICE</code> in <code>.env</code>.
              </div>
            )}

            {caps && !caps.virtual_microphone && (
              <div className="alert-box alert-warn" style={{ margin: 0 }}>
                <Icon name="info" size={16} />
                No reply microphone configured — {assistantName}&apos;s spoken answers play only in this dashboard, not in the meeting itself. Set <code style={{ margin: "0 4px" }}>BOT_VIRTUAL_MIC_LABEL</code> in <code>.env</code> to fix this.
              </div>
            )}

            <div style={{ background: "var(--bg-subtle)", padding: 22, borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)", display: "flex", flexDirection: "column", gap: 15 }}>
              <div>
                <h4 style={{ fontSize: 14.5, marginBottom: 4 }}>Test {assistantName}&apos;s voice reply</h4>
                <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>Say something with the &quot;{wakeWord}&quot; wake word — this simulates a spoken question without needing a live meeting.</p>
              </div>
              <form onSubmit={handleTestAssistantReply} style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <div style={{ position: "relative", flex: 1, minWidth: 240 }}>
                  <input type="text" className="form-input" style={{ paddingRight: voiceSupported ? 40 : undefined }} placeholder={testListening ? "Listening…" : `e.g. "${wakeWord}, what are our key action items?"`} value={assistantTestInput} onChange={(e) => setAssistantTestInput(e.target.value)} disabled={testingAssistant} />
                  {voiceSupported && (
                    <button
                      type="button"
                      onClick={() => toggleTestVoice(setAssistantTestInput)}
                      disabled={testingAssistant}
                      title={testListening ? "Stop listening" : "Ask by voice"}
                      style={{ position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)", width: 26, height: 26, borderRadius: "var(--radius-full)", border: "none", background: testListening ? "var(--accent-rose)" : "transparent", color: testListening ? "var(--text-on-accent)" : "var(--text-muted)", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}
                    >
                      <Icon name="mic" size={13} />
                    </button>
                  )}
                </div>
                <button type="submit" className="btn btn-primary btn-lg" disabled={testingAssistant || !assistantTestInput.trim()}>
                  {testingAssistant ? <span style={{ display: "flex", alignItems: "center", gap: 8 }}><Waveform size={15} active /> Synthesizing…</span> : <><Icon name="mic" size={15} /> Ask</>}
                </button>
              </form>

              <div>
                <h5 style={{ fontSize: 13, marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
                  <Icon name="volume" size={13} /> Reply stream <span className="badge badge-indigo">{assistantReplies.length}</span>
                </h5>
                {assistantReplies.length === 0 ? (
                  <div style={{ textAlign: "center", padding: "20px 14px", background: "var(--bg-surface)", borderRadius: "var(--radius-sm)", border: "1px dashed var(--border-card)", color: "var(--text-muted)", fontSize: 12.5 }}>
                    No replies yet — ask something above.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 12, maxHeight: 340, overflowY: "auto" }}>
                    {assistantReplies.map((reply) => (
                      <div key={reply.id} style={{ background: "var(--bg-surface)", border: "1px solid var(--border-card)", borderRadius: "var(--radius-md)", padding: 14, display: "flex", flexDirection: "column", gap: 9 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: "var(--text-muted)" }}>
                          <span className="badge badge-indigo">&quot;{reply.question}&quot;</span>
                          <span>{reply.timestamp}</span>
                        </div>
                        <div style={{ background: "var(--bg-subtle)", padding: 11, borderRadius: "var(--radius-sm)", fontSize: 12.5, lineHeight: 1.6 }}>{reply.answer}</div>
                        {reply.audio_base64 && <audio controls autoPlay src={`data:audio/wav;base64,${reply.audio_base64}`} style={{ width: "100%", height: 34 }} />}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="launch-card" style={{ margin: 0 }}>
              <span className="eyebrow"><Icon name="radio" size={12} /> Meeting assistant</span>
              <h2>Send the assistant into this meeting</h2>
              <p className="launch-sub">Paste a Zoom or Google Meet link. The assistant joins as a participant, transcribes Urdu and English, answers on &quot;{wakeWord}&quot;, and writes the notes when it leaves.</p>

              <div className="launch-row">
                <input type="text" className="form-input" placeholder="https://zoom.us/j/…  ·  https://meet.google.com/abc-defg-hij" value={meetingLink} onChange={(e) => setMeetingLink(e.target.value)} disabled={agentBusy || agentIsActive} />
                <button type="button" onClick={handleAgentToggle} className={`btn btn-lg ${agentIsActive ? "btn-danger" : "btn-primary"}`} disabled={agentBusy}>
                  {agentBusy ? <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span className="spinner" /> Working…</span> : agentIsActive ? "Leave & write notes" : agentState === "FAILED_JOIN" ? "Retry join" : "Join meeting"}
                </button>
              </div>

              <label className="launch-consent">
                <input type="checkbox" checked={recordAudio} onChange={(e) => setRecordAudio(e.target.checked)} disabled={agentBusy || agentIsActive} />
                <span>Record the meeting audio to disk — off by default. Tell participants before turning this on.</span>
              </label>

              {agentSimulated && (
                <div className="alert-box alert-warn" style={{ marginTop: 14, marginBottom: 0 }}>
                  <Icon name="alert" size={15} />
                  <span><strong>Simulated mode.</strong> The browser or audio devices aren&apos;t set up on the server, so no real meeting audio is captured. See <code style={{ margin: "0 4px" }}>docs/browser-bot-setup.md</code>.</span>
                </div>
              )}

              {agentParticipants.length > 0 && (
                <div className="roster-line" style={{ marginTop: 14 }}>
                  <strong>In the room:</strong> {agentParticipants.join(", ")}
                  {activeSpeaker && activeSpeaker !== "Speaker" && <span> · Speaking now: <strong>{activeSpeaker}</strong></span>}
                </div>
              )}

              {liveTranscripts.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <h5 style={{ fontSize: 12.5, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}><Icon name="message" size={12} /> Live transcript ({liveTranscripts.length})</h5>
                  <div style={{ background: "var(--bg-subtle)", padding: 12, borderRadius: "var(--radius-sm)", maxHeight: 170, overflowY: "auto", fontSize: 12, display: "flex", flexDirection: "column", gap: 6, border: "1px solid var(--border-subtle)" }}>
                    {liveTranscripts.map((t, i) => (
                      <div key={i} style={{ color: "var(--text-secondary)" }}><strong style={{ color: "var(--accent-indigo)" }}>[{t.timestamp}] {t.speaker}:</strong> {t.text}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
