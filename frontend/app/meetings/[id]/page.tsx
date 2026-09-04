"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import LiveRecorder from "@/app/components/LiveRecorder";
import {
  ActionItem,
  api,
  authStorage,
  Decision,
  MeetingDetail,
  MeetingInsights,
  Recording,
  Segment,
  Speaker,
} from "@/lib/api";

export default function MeetingDetailPage() {
  const params = useParams();
  const router = useRouter();
  const meetingId = Number(params.id);

  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [activeTab, setActiveTab] = useState<"summary" | "decisions" | "tasks" | "transcript" | "chat" | "agent" | "insights">("summary");
  const [insights, setInsights] = useState<MeetingInsights | null>(null);

  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Search in transcript
  const [transcriptSearch, setTranscriptSearch] = useState("");

  // Action items inline form
  const [newTaskText, setNewTaskText] = useState("");
  const [newTaskAssignee, setNewTaskAssignee] = useState("");
  const [newTaskDeadline, setNewTaskDeadline] = useState("");
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

  // Agent status
  const [agentState, setAgentState] = useState<string>("idle");
  const [agentBusy, setAgentBusy] = useState(false);
  const [zoomUrlOrId, setZoomUrlOrId] = useState("");
  const [zoomAuthorizing, setZoomAuthorizing] = useState(false);
  const [currentUserRole, setCurrentUserRole] = useState<string>("");

  // Ava Voice Reply + Realtime WS
  const [wsConnected, setWsConnected] = useState(false);
  const [avaReplies, setAvaReplies] = useState<
    { id: string; question: string; answer: string; audio_base64: string; timestamp: string }[]
  >([]);
  const [liveTranscripts, setLiveTranscripts] = useState<
    { speaker: string; text: string; timestamp: string }[]
  >([]);
  const [avaTestInput, setAvaTestInput] = useState("");
  const [testingAva, setTestingAva] = useState(false);

  useEffect(() => {
    if (!authStorage.isLoggedIn()) {
      router.push("/login");
      return;
    }
    if (isNaN(meetingId)) {
      setLoading(false);
      setError("Invalid Meeting ID in URL. Please select a valid meeting from your dashboard or click 'Meetings' in the top navbar.");
      return;
    }
    if (meetingId) {
      loadMeetingData();
    }
  }, [meetingId, router]);

  useEffect(() => {
    if (!authStorage.isLoggedIn()) return;
    api.getMe().then((user) => setCurrentUserRole(user.role || "employee")).catch(() => undefined);
    const refreshAgentStatus = () => {
      api.getZoomStatus(meetingId).then((status) => setAgentState(status.status || "idle")).catch(() => undefined);
    };
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
          const data = JSON.parse(event.data);
          if (data.event === "agent_state") {
            setAgentState(data.state || "idle");
          } else if (data.event === "ava_reply") {
            setAvaReplies((prev) => [
              {
                id: String(Date.now()),
                question: data.question || "",
                answer: data.answer || "",
                audio_base64: data.audio_base64 || "",
                timestamp: new Date().toLocaleTimeString(),
              },
              ...prev,
            ]);
          } else if (data.event === "transcript_live") {
            setLiveTranscripts((prev) => [
              ...prev,
              {
                speaker: data.speaker || "Speaker",
                text: data.text || "",
                timestamp: new Date().toLocaleTimeString(),
              },
            ]);
          }
        } catch {}
      };
      ws.onclose = () => setWsConnected(false);
      ws.onerror = () => setWsConnected(false);
    } catch {
      setWsConnected(false);
    }
    return () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    };
  }, [meetingId]);

  async function handleTestAvaReply(e: FormEvent) {
    e.preventDefault();
    if (!avaTestInput.trim() || testingAva) return;

    setTestingAva(true);
    setError("");
    try {
      const result = await api.testVoiceReply(meetingId, avaTestInput.trim());
      setAvaReplies((prev) => [
        {
          id: String(Date.now()),
          question: result.question,
          answer: result.answer,
          audio_base64: result.audio_base64,
          timestamp: new Date().toLocaleTimeString(),
        },
        ...prev,
      ]);
      setAvaTestInput("");
    } catch (err: any) {
      setError(err?.message || "Failed to generate Ava voice reply.");
    } finally {
      setTestingAva(false);
    }
  }

  async function loadMeetingData() {
    setLoading(true);
    setError("");
    try {
      const [detail, recData, speakersData, zoomData] = await Promise.all([
        api.getMeeting(meetingId),
        api.getRecording(meetingId).catch(() => null),
        api.getSpeakers(meetingId).catch(() => []),
        api.getZoomStatus(meetingId).catch(() => ({ status: "idle" })),
      ]);

      setMeeting(detail);
      setInsights(await api.getMeetingInsights(meetingId).catch(() => null));
      setRecording(recData);
      setSpeakers(speakersData);
      setAgentState(zoomData.status || "idle");
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
      setSuccess(`Audio transcribed successfully (${result.segment_count || 0} segments extracted).`);
      const [detail, speakersData] = await Promise.all([
        api.getMeeting(meetingId),
        api.getSpeakers(meetingId),
      ]);
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
      setError("Please upload an audio file or record live speech first.");
      return;
    }

    setAnalyzing(true);
    setError("");
    setSuccess("");

    try {
      await api.analyzeMeeting(meetingId);
      setSuccess("Analysis complete! Summary, key decisions, and action items updated.");
      const detail = await api.getMeeting(meetingId);
      setMeeting(detail);
      setActiveTab("summary");
    } catch (err: any) {
      setError(err?.message || "AI Analysis failed.");
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleToggleRecording() {
    if (!recording) return;
    const newEnabled = !recording.enabled;
    try {
      const updated = await api.toggleRecording(meetingId, newEnabled);
      setRecording(updated);
      setSuccess(
        newEnabled
          ? "Recording enabled with attendee consent tracking."
          : "Recording disabled (live transcript only, no audio saved)."
      );
    } catch (err: any) {
      setError(err?.message || "Failed to update recording settings");
    }
  }

  async function handleRenameSpeaker(speakerId: number) {
    if (!editSpeakerName.trim()) {
      setEditingSpeakerId(null);
      return;
    }

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
      setChatMessages((prev) => [
        ...prev,
        { sender: "ai", text: response.answer, sources: response.sources },
      ]);
    } catch (err: any) {
      setChatMessages((prev) => [
        ...prev,
        { sender: "ai", text: "I encountered an issue retrieving the answer from the transcript. Please try again." },
      ]);
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
    const updatedSegments = [...(meeting.segments || []), newSeg];
    const updatedTranscript = `${meeting.transcript || ""} ${newSeg.text}`.trim();
    setMeeting({
      ...meeting,
      segments: updatedSegments,
      transcript: updatedTranscript,
    });
  }

  function handleLiveActionCreated(taskText: string) {
    setSuccess(`Auto-detected live action item: "${taskText}"`);
    loadMeetingData();
  }

  async function handleToggleTaskStatus(taskId: number, currentStatus: string) {
    const nextStatus = currentStatus === "done" ? "pending" : "done";
    try {
      const updatedItem = await api.updateTask(taskId, { status: nextStatus });
      if (meeting) {
        setMeeting({
          ...meeting,
          action_items: meeting.action_items.map((item) =>
            item.id === taskId ? updatedItem : item
          ),
        });
      }
    } catch (err: any) {
      setError(err?.message || "Failed to update task");
    }
  }

  async function handleDeleteTask(taskId: number) {
    try {
      await api.deleteTask(taskId);
      if (meeting) {
        setMeeting({
          ...meeting,
          action_items: meeting.action_items.filter((item) => item.id !== taskId),
        });
      }
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
        assignee: newTaskAssignee.trim() || undefined,
        deadline: newTaskDeadline.trim() || undefined,
      });

      if (meeting) {
        setMeeting({
          ...meeting,
          action_items: [created, ...(meeting.action_items || [])],
        });
      }

      setNewTaskText("");
      setNewTaskAssignee("");
      setNewTaskDeadline("");
      setSuccess(`Action item assigned to ${created.assignee || "Unassigned"} and tracked.`);
    } catch (err: any) {
      setError(err?.message || "Failed to create task");
    } finally {
      setAddingTask(false);
    }
  }

  async function handleAgentToggle() {
    if ((agentState === "idle" || agentState === "stopped" || agentState === "left") && !zoomUrlOrId.trim()) {
      setError("Enter a Zoom meeting URL or meeting ID first.");
      return;
    }
    setAgentBusy(true);
    setError("");
    try {
      if (agentState === "idle" || agentState === "stopped" || agentState === "left") {
        const result = await api.joinZoomMeeting(meetingId, zoomUrlOrId.trim());
        setAgentState("listening");
        setSuccess(result.message || "Zoom agent connected to the meeting stream.");
      } else {
        const result = await api.leaveZoomMeeting(meetingId);
        setAgentState("left");
        setSuccess(result.message || "Zoom agent disconnected.");
      }
    } catch (err: any) {
      setError(err?.message || "Failed to update agent state");
    } finally {
      setAgentBusy(false);
    }
  }

  async function handleZoomAuthorize() {
    setZoomAuthorizing(true);
    try {
      const result = await api.getZoomAuthorizationUrl();
      window.location.href = result.authorization_url;
    } catch (err: any) {
      setError(err?.message || "Could not start Zoom authorization.");
      setZoomAuthorizing(false);
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
    return text
      .split(/\n+|(?<=[.!?])\s+(?=[A-Z])/)
      .map((line) => line.replace(/^[-•*]\s*/, "").trim())
      .filter(Boolean);
  }

  function getAgentPresentation(state: string) {
    const s = (state || "idle").toLowerCase();
    const states: Record<string, { label: string; badge: string }> = {
      idle: { label: "Idle / Scheduled", badge: "badge-indigo" },
      joining: { label: "Joining Zoom...", badge: "badge-amber" },
      listening: { label: "In Meeting & Listening", badge: "badge-emerald" },
      in_meeting: { label: "In Meeting & Listening", badge: "badge-emerald" },
      processing: { label: "Processing Transcript", badge: "badge-cyan" },
      complete: { label: "Session Complete", badge: "badge-emerald" },
      leaving: { label: "Disconnecting...", badge: "badge-amber" },
      stopped: { label: "Disconnected", badge: "badge-rose" },
      disconnected: { label: "Disconnected", badge: "badge-rose" },
      failed_join: { label: "Failed Join - Retry", badge: "badge-rose" },
    };
    return states[s] || { label: state.replaceAll("_", " "), badge: "badge-amber" };
  }

  if (loading) {
    return (
      <div className="app-container" style={{ textAlign: "center", padding: "120px 0" }}>
        <div className="spinner" style={{ margin: "0 auto 16px", width: 28, height: 28, borderWidth: 3 }}></div>
        <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>Loading meeting workspace...</p>
      </div>
    );
  }

  if (!meeting) {
    return (
      <div className="app-container" style={{ textAlign: "center", padding: "80px 0" }}>
        <h2 style={{ marginBottom: 16 }}>Meeting not found</h2>
        <Link href="/meetings" className="btn btn-primary">
          Back to Meetings
        </Link>
      </div>
    );
  }

  const filteredSegments = (meeting.segments || []).filter((s) =>
    s.text.toLowerCase().includes(transcriptSearch.toLowerCase())
  );

  return (
    <div className="app-container">
      {/* Breadcrumb Navigation */}
      <div style={{ marginBottom: 16 }}>
        <Link
          href="/meetings"
          style={{
            fontSize: 13,
            color: "var(--text-secondary)",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontWeight: 500,
          }}
        >
          <span>←</span>
          <span>Back to Workspaces</span>
        </Link>
      </div>

      {/* Header Control Panel */}
      <div
        className="glass-panel"
        style={{
          marginBottom: 20,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 20,
          padding: "24px 28px",
          borderLeft: "4px solid var(--accent-indigo)",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
            <h1 style={{ fontSize: 22, color: "#ffffff" }}>{meeting.title}</h1>
            <span className="badge badge-cyan">{meeting.platform || "Direct Audio"}</span>
            {meeting.transcript && <span className="badge badge-emerald">Transcribed</span>}
          </div>
          <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
            Session ID: #{meeting.id} • Created:{" "}
            {meeting.created_at
              ? new Date(meeting.created_at).toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })
              : "Recently"}
          </p>
        </div>

        {/* Action Controls Toolbar */}
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          {/* Recording Toggle (Default OFF Rule) */}
          <button
            onClick={handleToggleRecording}
            className={`btn btn-sm ${recording?.enabled ? "btn-danger" : "btn-secondary"}`}
            title="Recording consent toggle"
          >
            {recording?.enabled ? "🔴 Recording: ON" : "⚪ Record: OFF"}
          </button>

          {/* Upload Audio Button */}
          <label className="btn btn-secondary btn-sm" style={{ cursor: uploading ? "wait" : "pointer" }}>
            {uploading ? (
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span className="spinner" />
                <span>Transcribing...</span>
              </span>
            ) : (
              <span>📤 Upload Audio</span>
            )}
            <input
              type="file"
              accept="audio/*"
              hidden
              disabled={uploading}
              onChange={handleAudioUpload}
            />
          </label>

          {/* Analyze Meeting Button */}
          <button
            onClick={handleAnalyze}
            className="btn btn-primary btn-sm"
            disabled={analyzing || !meeting.transcript}
          >
            {analyzing ? (
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span className="spinner" />
                <span>AI Analyzing...</span>
              </span>
            ) : (
              <span>⚡ Generate Notes</span>
            )}
          </button>
        </div>
      </div>

      {/* Live Voice Stream Capture Component */}
      <LiveRecorder
        meetingId={meetingId}
        onNewSegment={handleLiveSegment}
        onLiveActionCreated={handleLiveActionCreated}
      />

      {/* Alerts */}
      {error && <div className="alert-box alert-error">{error}</div>}
      {success && <div className="alert-box alert-success">{success}</div>}

      {/* Tab Navigation */}
      <div className="tabs-nav">
        <button
          className={`tab-btn ${activeTab === "summary" ? "active" : ""}`}
          onClick={() => setActiveTab("summary")}
        >
          <span>📄</span>
          <span>Executive Summary</span>
        </button>
        {currentUserRole === "admin" && (
          <button className={`tab-btn ${activeTab === "insights" ? "active" : ""}`} onClick={() => setActiveTab("insights")}>
            <span>◌</span>
            <span>Insights</span>
          </button>
        )}
        <button
          className={`tab-btn ${activeTab === "decisions" ? "active" : ""}`}
          onClick={() => setActiveTab("decisions")}
        >
          <span>⚖️</span>
          <span>Decisions ({meeting.decisions?.length || 0})</span>
        </button>
        <button
          className={`tab-btn ${activeTab === "tasks" ? "active" : ""}`}
          onClick={() => setActiveTab("tasks")}
        >
          <span>🎯</span>
          <span>Action Items ({meeting.action_items?.length || 0})</span>
        </button>
        <button
          className={`tab-btn ${activeTab === "transcript" ? "active" : ""}`}
          onClick={() => setActiveTab("transcript")}
        >
          <span>🎙️</span>
          <span>Transcript Timeline ({meeting.segments?.length || (meeting.transcript ? 1 : 0)})</span>
        </button>
        <button
          className={`tab-btn ${activeTab === "chat" ? "active" : ""}`}
          onClick={() => setActiveTab("chat")}
        >
          <span>💬</span>
          <span>AI Meeting Copilot</span>
        </button>
        <button
          className={`tab-btn ${activeTab === "agent" ? "active" : ""}`}
          onClick={() => setActiveTab("agent")}
        >
          <span>🤖</span>
          <span>Zoom Agent & Ava Voice</span>
        </button>
      </div>

      {/* Main Workspace Panels */}
      <div className="glass-panel" style={{ minHeight: 420, padding: 28 }}>
        {/* SUMMARY TAB */}
        {activeTab === "summary" && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
              <div>
                <h3 style={{ fontSize: 18, marginBottom: 4 }}>Executive Summary & Highlights</h3>
                <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
                  Synthesized automatically from the complete meeting transcript
                </span>
              </div>
              {meeting.summary && (
                <span className="badge badge-purple">
                  Engine: {meeting.summary.provider || "Ollama Local LLM"}
                </span>
              )}
            </div>

            {meeting.summary?.text ? (
              <div
                style={{
                  background: "var(--bg-input)",
                  padding: 24,
                  borderRadius: "var(--radius-md)",
                  lineHeight: 1.7,
                  fontSize: 15,
                  whiteSpace: "pre-wrap",
                  border: "1px solid var(--border-subtle)",
                  color: "var(--text-primary)",
                }}
              >
                <ul style={{ display: "grid", gap: 12, paddingLeft: 20, margin: 0 }}>
                  {formatSummary(meeting.summary.text).map((point, index) => <li key={index}>{point}</li>)}
                </ul>
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "60px 20px", color: "var(--text-muted)" }}>
                <div style={{ fontSize: 36, marginBottom: 12 }}>📄</div>
                <h4 style={{ fontSize: 16, color: "#fff", marginBottom: 6 }}>No summary generated yet</h4>
                <p style={{ marginBottom: 18, fontSize: 13, color: "var(--text-secondary)" }}>
                  {meeting.transcript
                    ? "Click the button below to extract summary, decisions, and action items using AI."
                    : "Upload an audio recording or use the Live Mic above to generate transcript."}
                </p>
                {meeting.transcript && (
                  <button onClick={handleAnalyze} className="btn btn-primary btn-sm" disabled={analyzing}>
                    {analyzing ? "Synthesizing Notes..." : "Generate AI Summary"}
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {/* DECISIONS TAB */}
        {activeTab === "decisions" && (
          <div>
            <div style={{ marginBottom: 20 }}>
              <h3 style={{ fontSize: 18, marginBottom: 4 }}>Key Decisions Log</h3>
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
                Explicit agreements and architectural/business conclusions reached during the meeting
              </span>
            </div>

            {meeting.decisions && meeting.decisions.length > 0 ? (
              <div style={{ display: "grid", gap: 14 }}>
                {meeting.decisions.map((d, index) => (
                  <div
                    key={d.id || index}
                    style={{
                      background: "var(--bg-input)",
                      padding: "16px 20px",
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid rgba(16, 185, 129, 0.2)",
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 14,
                    }}
                  >
                    <div
                      style={{
                        width: 28,
                        height: 28,
                        borderRadius: "50%",
                        background: "rgba(16, 185, 129, 0.12)",
                        color: "#34d399",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 14,
                        fontWeight: 700,
                        flexShrink: 0,
                      }}
                    >
                      ✓
                    </div>
                    <div style={{ flex: 1 }}>
                      <p style={{ fontSize: 15, lineHeight: 1.5, color: "var(--text-primary)" }}>
                        {d.text}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "60px 20px", color: "var(--text-muted)" }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>⚖️</div>
                <p style={{ fontSize: 14 }}>No decisions recorded yet. Run analysis to extract decisions.</p>
              </div>
            )}
          </div>
        )}

        {/* TASKS & ACTION ITEMS TAB */}
        {activeTab === "tasks" && (
          <div>
            <div style={{ marginBottom: 20 }}>
              <h3 style={{ fontSize: 18, marginBottom: 4 }}>Action Items & Assignments</h3>
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
                Autonomous task extraction with assignees, assigners, and deadlines
              </span>
            </div>

            {/* Add Task Form */}
            <form
              onSubmit={handleCreateTask}
              style={{
                display: "grid",
                gridTemplateColumns: "2fr 1fr 1fr auto",
                gap: 10,
                marginBottom: 24,
                background: "var(--bg-input)",
                padding: 16,
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-subtle)",
              }}
            >
              <input
                type="text"
                className="form-input"
                placeholder="Task description (e.g. Implement Zoom RTMS connector)..."
                value={newTaskText}
                onChange={(e) => setNewTaskText(e.target.value)}
                required
              />
              <input
                type="text"
                className="form-input"
                placeholder="Assignee (e.g. Hamza)"
                value={newTaskAssignee}
                onChange={(e) => setNewTaskAssignee(e.target.value)}
              />
              <input
                type="text"
                className="form-input"
                placeholder="Deadline (e.g. Friday 5 PM)"
                value={newTaskDeadline}
                onChange={(e) => setNewTaskDeadline(e.target.value)}
              />
              <button type="submit" className="btn btn-primary btn-sm" disabled={addingTask || !newTaskText.trim()}>
                {addingTask ? "Adding..." : "+ Assign Task"}
              </button>
            </form>

            {/* Task List */}
            {meeting.action_items && meeting.action_items.length > 0 ? (
              <div style={{ display: "grid", gap: 10 }}>
                {meeting.action_items.map((item) => (
                  <div
                    key={item.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 16,
                      background: "var(--bg-input)",
                      padding: "16px 20px",
                      borderRadius: "var(--radius-sm)",
                      border: item.status === "done" ? "1px solid rgba(255, 255, 255, 0.04)" : "1px solid var(--border-card)",
                      transition: "all 0.15s ease",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 14, flex: 1 }}>
                      <input
                        type="checkbox"
                        checked={item.status === "done"}
                        onChange={() => handleToggleTaskStatus(item.id, item.status)}
                        style={{
                          width: 18,
                          height: 18,
                          cursor: "pointer",
                          accentColor: "var(--accent-indigo)",
                        }}
                      />
                      <div>
                        <p
                          style={{
                            fontSize: 15,
                            fontWeight: 500,
                            marginBottom: 4,
                            textDecoration: item.status === "done" ? "line-through" : "none",
                            color: item.status === "done" ? "var(--text-muted)" : "var(--text-primary)",
                          }}
                        >
                          {item.task}
                        </p>
                        <div style={{ display: "flex", gap: 14, fontSize: 12, color: "var(--text-muted)", flexWrap: "wrap" }}>
                          {item.assignee && (
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "#a5b4fc" }}>
                              👤 Assignee: {item.assignee}
                            </span>
                          )}
                          {item.assigned_by && (
                            <span style={{ color: "var(--text-muted)" }}>
                              From: {item.assigned_by}
                            </span>
                          )}
                          {item.deadline && (
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "#fde047" }}>
                              ⏰ Due: {item.deadline}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    <button
                      onClick={() => handleDeleteTask(item.id)}
                      className="btn btn-secondary btn-sm"
                      style={{ padding: "4px 10px", fontSize: 12, color: "var(--accent-rose)" }}
                      title="Delete task"
                    >
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "50px 20px", color: "var(--text-muted)" }}>
                <p style={{ fontSize: 14 }}>No action items recorded yet.</p>
              </div>
            )}
          </div>
        )}

        {activeTab === "insights" && (
          <div>
            <div style={{ marginBottom: 20 }}>
              <h3 style={{ fontSize: 18, marginBottom: 4 }}>Participation Insights</h3>
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
                Talk-time and engagement calculated from the timestamped transcript.
              </span>
            </div>
            {insights?.participants.length ? (
              <div style={{ display: "grid", gap: 12 }}>
                {insights.participants.map((participant) => (
                  <div key={participant.speaker} style={{ padding: 16, background: "var(--bg-input)", border: "1px solid var(--border-card)", borderRadius: "var(--radius-sm)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
                      <strong>{getSpeakerDisplayName(participant.speaker)}</strong>
                      <span className="badge badge-cyan">{participant.engagement_score}% engaged</span>
                    </div>
                    <div style={{ height: 8, background: "var(--border-subtle)", borderRadius: 4, overflow: "hidden", marginBottom: 9 }}>
                      <div style={{ width: `${participant.talk_time_percent}%`, height: "100%", background: "var(--accent-primary)" }} />
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text-secondary)", fontSize: 12 }}>
                      <span>{Math.round(participant.talk_time_seconds)}s speaking</span>
                      <span>{participant.talk_time_percent}% of talk-time</span>
                    </div>
                    <p style={{ marginTop: 10, color: "var(--text-secondary)", fontSize: 13 }}>{participant.coaching_tip}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "60px 20px", color: "var(--text-muted)" }}>
                Add a transcript with speaker timestamps to calculate insights.
              </div>
            )}
          </div>
        )}

        {/* TRANSCRIPT TIMELINE TAB */}
        {activeTab === "transcript" && (
          <div>
            {/* Identified Speakers Bar */}
            {speakers.length > 0 && (
              <div
                style={{
                  background: "var(--bg-input)",
                  padding: "14px 18px",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border-subtle)",
                  marginBottom: 20,
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  flexWrap: "wrap",
                }}
              >
                <span style={{ fontSize: 13, fontWeight: 700, color: "var(--text-secondary)" }}>
                  Identified Speakers:
                </span>
                {speakers.map((spk) => (
                  <div key={spk.id} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    {editingSpeakerId === spk.id ? (
                      <div style={{ display: "flex", gap: 4 }}>
                        <input
                          type="text"
                          className="form-input"
                          style={{ padding: "4px 10px", fontSize: 12, width: 140 }}
                          value={editSpeakerName}
                          onChange={(e) => setEditSpeakerName(e.target.value)}
                          placeholder="Speaker name..."
                          autoFocus
                        />
                        <button
                          onClick={() => handleRenameSpeaker(spk.id)}
                          className="btn btn-primary btn-sm"
                          style={{ padding: "3px 10px", fontSize: 11 }}
                          disabled={updatingSpeaker}
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setEditingSpeakerId(null)}
                          className="btn btn-secondary btn-sm"
                          style={{ padding: "3px 8px", fontSize: 11 }}
                        >
                          ✕
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => {
                          setEditingSpeakerId(spk.id);
                          setEditSpeakerName(spk.display_name || spk.speaker_label);
                        }}
                        className="badge badge-indigo"
                        style={{ cursor: "pointer" }}
                        title="Click to rename speaker"
                      >
                        <span>{spk.display_name || spk.speaker_label}</span>
                        <span style={{ opacity: 0.7, fontSize: 11 }}>✎</span>
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 18,
                flexWrap: "wrap",
                gap: 12,
              }}
            >
              <div>
                <h3 style={{ fontSize: 18, marginBottom: 2 }}>Transcript Timeline</h3>
                <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
                  Timestamped segments from speech recognition engine
                </span>
              </div>

              <input
                type="text"
                className="form-input"
                placeholder="Search transcript..."
                style={{ width: 240, padding: "8px 14px", fontSize: 13 }}
                value={transcriptSearch}
                onChange={(e) => setTranscriptSearch(e.target.value)}
              />
            </div>

            {meeting.segments && meeting.segments.length > 0 ? (
              <div
                style={{
                  display: "grid",
                  gap: 12,
                  maxHeight: 520,
                  overflowY: "auto",
                  paddingRight: 6,
                }}
              >
                {filteredSegments.map((seg, idx) => (
                  <div
                    key={seg.id || idx}
                    style={{
                      background: "var(--bg-input)",
                      padding: "14px 18px",
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid var(--border-subtle)",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        fontSize: 12,
                        color: "var(--text-muted)",
                        marginBottom: 6,
                      }}
                    >
                      <span className="badge badge-cyan" style={{ fontSize: 11 }}>
                        {getSpeakerDisplayName(seg.speaker_label)}
                      </span>
                      <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                        [{formatTime(seg.start_time)} - {formatTime(seg.end_time)}]
                      </span>
                    </div>
                    <p style={{ fontSize: 14, lineHeight: 1.6, color: "var(--text-primary)" }}>{seg.text}</p>
                  </div>
                ))}
              </div>
            ) : meeting.transcript ? (
              <div
                style={{
                  background: "var(--bg-input)",
                  padding: 20,
                  borderRadius: "var(--radius-sm)",
                  lineHeight: 1.7,
                  fontSize: 14,
                  whiteSpace: "pre-wrap",
                  color: "var(--text-primary)",
                }}
              >
                {meeting.transcript}
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "60px 20px", color: "var(--text-muted)" }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>🎙️</div>
                <p style={{ marginBottom: 16, fontSize: 14 }}>No transcript available for this session.</p>
                <label className="btn btn-primary btn-sm" style={{ cursor: "pointer" }}>
                  Upload Audio Recording
                  <input type="file" accept="audio/*" hidden onChange={handleAudioUpload} />
                </label>
              </div>
            )}
          </div>
        )}

        {/* AI MEETING COPILOT & VOICE Q&A TAB */}
        {activeTab === "chat" && (
          <div>
            <div style={{ marginBottom: 18 }}>
              <h3 style={{ fontSize: 18, marginBottom: 4 }}>Meeting Q&A Copilot</h3>
              <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
                Ask questions grounded directly in this meeting&apos;s audio transcript, decisions, and action items.
              </p>
            </div>

            {/* Quick Suggestion Chips */}
            <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
              <button
                type="button"
                onClick={() => handleSendChatMessage("What are the key decisions made in this meeting?")}
                className="btn btn-secondary btn-sm"
                style={{ fontSize: 12 }}
                disabled={chatLoading}
              >
                ⚖️ Key Decisions?
              </button>
              <button
                type="button"
                onClick={() => handleSendChatMessage("Who was assigned tasks and what are their deadlines?")}
                className="btn btn-secondary btn-sm"
                style={{ fontSize: 12 }}
                disabled={chatLoading}
              >
                🎯 Assigned Tasks?
              </button>
              <button
                type="button"
                onClick={() => handleSendChatMessage("Summarize the main discussion points in 3 concise bullets.")}
                className="btn btn-secondary btn-sm"
                style={{ fontSize: 12 }}
                disabled={chatLoading}
              >
                📑 3-Bullet Summary
              </button>
            </div>

            {/* Chat Messages Container */}
            <div
              style={{
                background: "var(--bg-input)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-md)",
                padding: 20,
                minHeight: 280,
                maxHeight: 420,
                overflowY: "auto",
                display: "flex",
                flexDirection: "column",
                gap: 14,
                marginBottom: 16,
              }}
            >
              {chatMessages.length === 0 ? (
                <div style={{ textAlign: "center", padding: "50px 0", color: "var(--text-muted)", fontSize: 14 }}>
                  Ask any question about this meeting or click one of the quick suggestions above.
                </div>
              ) : (
                chatMessages.map((msg, idx) => (
                  <div
                    key={idx}
                    style={{
                      alignSelf: msg.sender === "user" ? "flex-end" : "flex-start",
                      maxWidth: "85%",
                      background: msg.sender === "user" ? "var(--accent-gradient)" : "var(--bg-card)",
                      color: "#ffffff",
                      padding: "12px 18px",
                      borderRadius: "var(--radius-md)",
                      border: msg.sender === "ai" ? "1px solid var(--border-card)" : "none",
                      fontSize: 14,
                      lineHeight: 1.6,
                      boxShadow: "var(--shadow-sm)",
                    }}
                  >
                    <p style={{ whiteSpace: "pre-wrap" }}>{msg.text}</p>

                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10, gap: 12 }}>
                      {msg.sources && msg.sources.length > 0 ? (
                        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                          Sources: {msg.sources.join(" · ")}
                        </span>
                      ) : <span />}

                      {msg.sender === "ai" && (
                        <button
                          type="button"
                          onClick={() => handleSpeakText(msg.text)}
                          className="btn btn-secondary btn-sm"
                          style={{ padding: "3px 8px", fontSize: 11 }}
                          title="Read aloud with Text-to-Speech"
                          disabled={playingTTS}
                        >
                          {playingTTS ? "🔊 Speaking..." : "🔊 Read Aloud"}
                        </button>
                      )}
                    </div>
                  </div>
                ))
              )}
              {chatLoading && (
                <div
                  style={{
                    alignSelf: "flex-start",
                    background: "var(--bg-card)",
                    padding: "12px 18px",
                    borderRadius: "var(--radius-md)",
                    border: "1px solid var(--border-card)",
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    fontSize: 13,
                    color: "var(--text-secondary)",
                  }}
                >
                  <span className="spinner" />
                  <span>Grounding answer in transcript context...</span>
                </div>
              )}
            </div>

            {/* Input Form */}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSendChatMessage();
              }}
              style={{ display: "flex", gap: 10 }}
            >
              <input
                type="text"
                className="form-input"
                placeholder="Ask about this meeting (e.g. What did the team conclude about deployment?)..."
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                disabled={chatLoading}
              />
              <button type="submit" className="btn btn-primary" disabled={chatLoading || !chatInput.trim()}>
                Ask AI
              </button>
            </form>
          </div>
        )}

        {/* ZOOM AUTONOMOUS BOT & AVA VOICE REPLY CONTROLLER TAB */}
        {activeTab === "agent" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            {/* Header & Status Bar */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
              <div>
                <h3 style={{ fontSize: 18, marginBottom: 4 }}>Zoom Agent & Ava Voice Reply Stream</h3>
                <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
                  Autonomous RTMS bot + &quot;Ava&quot; wake-word voice answers generated via Piper/pyttsx3 TTS.
                </p>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span className={`badge ${wsConnected ? "badge-emerald" : "badge-rose"}`}>
                  {wsConnected ? "🟢 Live WS Connected" : "⚪ WS Disconnected"}
                </span>
                <span
                  className={`badge ${getAgentPresentation(agentState).badge}`}
                  style={{ textTransform: "uppercase", padding: "6px 14px", fontSize: 13 }}
                >
                  Bot Status: {getAgentPresentation(agentState).label}
                </span>
              </div>
            </div>

            {/* Ava Active Listening Banner */}
            {(agentState.toLowerCase() === "listening" || agentState.toLowerCase() === "in_meeting") && (
              <div
                style={{
                  background: "rgba(16, 185, 129, 0.12)",
                  border: "1px solid rgba(16, 185, 129, 0.3)",
                  borderRadius: "var(--radius-md)",
                  padding: "14px 18px",
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  color: "#10b981",
                  fontWeight: 600,
                  fontSize: 14,
                }}
              >
                <span className="spinner" style={{ borderColor: "#10b981", borderTopColor: "transparent", width: 20, height: 20 }} />
                <span>🎤 Ava is actively listening in Zoom. Say &quot;Ava, what is the deployment status?&quot; to hear a voice reply!</span>
              </div>
            )}

            {/* Top Banner Card: Test Ava Voice Reply */}
            <div
              style={{
                background: "var(--bg-input)",
                padding: 24,
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-card)",
                display: "flex",
                flexDirection: "column",
                gap: 16,
              }}
            >
              <div>
                <h4 style={{ fontSize: 16, color: "#fff", marginBottom: 4 }}>🗣️ Test Ava Voice Reply (TTS Engine)</h4>
                <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                  Speak or ask a grounded question using the &quot;Ava&quot; wake-word. Ava will retrieve transcript RAG answers and synthesize audio using Piper/pyttsx3 TTS.
                </p>
              </div>

              <form onSubmit={handleTestAvaReply} style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                <input
                  type="text"
                  className="form-input"
                  style={{ flex: 1, minWidth: 260, fontSize: 14 }}
                  placeholder='Say something to Ava (e.g. "Ava, what are our key action items?")...'
                  value={avaTestInput}
                  onChange={(e) => setAvaTestInput(e.target.value)}
                  disabled={testingAva}
                />
                <button type="submit" className="btn btn-primary btn-lg" disabled={testingAva || !avaTestInput.trim()}>
                  {testingAva ? (
                    <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span className="spinner" />
                      <span>Synthesizing Voice...</span>
                    </span>
                  ) : (
                    "🎙️ Speak to Ava"
                  )}
                </button>
              </form>

              {/* Voice Reply Stream list */}
              <div>
                <h5 style={{ fontSize: 14, color: "var(--text-primary)", marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                  <span>🔊 Ava Voice Answers Stream</span>
                  <span className="badge badge-indigo">{avaReplies.length} Replies</span>
                </h5>

                {avaReplies.length === 0 ? (
                  <div
                    style={{
                      textAlign: "center",
                      padding: "24px 16px",
                      background: "var(--bg-card)",
                      borderRadius: "var(--radius-sm)",
                      border: "1px dashed var(--border-card)",
                      color: "var(--text-muted)",
                      fontSize: 13,
                    }}
                  >
                    No voice answers generated yet. Type a question with &quot;Ava&quot; above and click &quot;Speak to Ava&quot;!
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 14, maxHeight: 360, overflowY: "auto" }}>
                    {avaReplies.map((reply) => (
                      <div
                        key={reply.id}
                        style={{
                          background: "var(--bg-card)",
                          border: "1px solid var(--border-card)",
                          borderRadius: "var(--radius-md)",
                          padding: 16,
                          display: "flex",
                          flexDirection: "column",
                          gap: 10,
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text-muted)" }}>
                          <span className="badge badge-indigo">💬 Question: &quot;{reply.question}&quot;</span>
                          <span>{reply.timestamp}</span>
                        </div>
                        
                        <div style={{ background: "var(--bg-input)", padding: 12, borderRadius: "var(--radius-sm)", fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6 }}>
                          <strong style={{ color: "#10b981" }}>🤖 Ava Answer: </strong>
                          {reply.answer}
                        </div>

                        {reply.audio_base64 && (
                          <div style={{ marginTop: 4 }}>
                            <label style={{ fontSize: 11, color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
                              🔊 Voice Audio (Piper/pyttsx3 Output):
                            </label>
                            <audio
                              controls
                              autoPlay
                              src={`data:audio/wav;base64,${reply.audio_base64}`}
                              style={{ width: "100%", height: 36 }}
                            />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Bottom Card: Zoom Bot Controller */}
            <div
              style={{
                background: "var(--bg-input)",
                padding: 24,
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border-subtle)",
                display: "flex",
                flexDirection: "column",
                gap: 16,
              }}
            >
              <h4 style={{ fontSize: 15, color: "#fff", marginBottom: 2 }}>🤖 Zoom Autonomous Bot Controller</h4>
              <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                Launch the RTMS audio bot into your Zoom meeting room. The bot streams real-time audio, listens for the wake-word &quot;Ava&quot;, and generates spoken audio replies.
              </p>

              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                <input
                  type="text"
                  className="form-input"
                  style={{ flex: 1, minWidth: 280 }}
                  placeholder="e.g. https://zoom.us/j/849203948..."
                  value={zoomUrlOrId}
                  onChange={(e) => setZoomUrlOrId(e.target.value)}
                  disabled={agentBusy || agentState.toLowerCase() === "listening" || agentState.toLowerCase() === "in_meeting"}
                />
                <button
                  type="button"
                  onClick={handleAgentToggle}
                  className={`btn ${
                    agentState.toLowerCase() === "listening" || agentState.toLowerCase() === "in_meeting"
                      ? "btn-danger"
                      : "btn-primary"
                  }`}
                  disabled={agentBusy}
                >
                  {agentBusy ? (
                    <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                      <span className="spinner" />
                      <span>Communicating with Bot...</span>
                    </span>
                  ) : agentState.toLowerCase() === "listening" || agentState.toLowerCase() === "in_meeting" ? (
                    "Disconnect Bot from Zoom"
                  ) : agentState.toLowerCase() === "stopped" || agentState.toLowerCase() === "failed_join" ? (
                    "Retry Zoom Bot Join"
                  ) : (
                    "Launch Zoom Agent Bot"
                  )}
                </button>
              </div>

              <div
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border-card)",
                  borderRadius: "var(--radius-sm)",
                  padding: 14,
                  fontSize: 12,
                  lineHeight: 1.6,
                  color: "var(--text-secondary)",
                }}
              >
                <strong>OAuth Authorization Note:</strong> RTMS raw media audio stream requires an authorized Zoom Client ID.
                <div style={{ marginTop: 8 }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={handleZoomAuthorize}
                    disabled={zoomAuthorizing}
                  >
                    {zoomAuthorizing ? "Redirecting..." : "Authorize Zoom OAuth"}
                  </button>
                </div>
              </div>

              {/* Real-time WS Raw Transcript Stream */}
              {liveTranscripts.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <h5 style={{ fontSize: 13, color: "var(--text-primary)", marginBottom: 8 }}>
                    📡 Live RTMS Audio Stream Feed ({liveTranscripts.length})
                  </h5>
                  <div
                    style={{
                      background: "var(--bg-card)",
                      padding: 12,
                      borderRadius: "var(--radius-sm)",
                      maxHeight: 180,
                      overflowY: "auto",
                      fontSize: 12,
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                      border: "1px solid var(--border-card)",
                    }}
                  >
                    {liveTranscripts.map((t, i) => (
                      <div key={i} style={{ color: "var(--text-secondary)" }}>
                        <strong style={{ color: "#a5b4fc" }}>[{t.timestamp}] {t.speaker}:</strong> {t.text}
                      </div>
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
