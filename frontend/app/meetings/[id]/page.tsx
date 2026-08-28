"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import LiveRecorder from "@/app/components/LiveRecorder";
import {
  ActionItem,
  api,
  authStorage,
  ChatAnswer,
  Decision,
  MeetingDetail,
  Recording,
  Segment,
  Speaker,
  Summary,
} from "@/lib/api";

export default function MeetingDetailPage() {
  const params = useParams();
  const router = useRouter();
  const meetingId = Number(params.id);

  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [activeTab, setActiveTab] = useState<"summary" | "decisions" | "tasks" | "transcript" | "chat" | "agent">("summary");

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

  // AI Meeting Chat state (Block 2) + TTS (Block 3)
  const [chatMessages, setChatMessages] = useState<{ sender: "user" | "ai"; text: string; sources?: string[] }[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [playingTTS, setPlayingTTS] = useState(false);

  // Agent status
  const [agentState, setAgentState] = useState<string>("idle");
  const [agentBusy, setAgentBusy] = useState(false);

  useEffect(() => {
    if (!authStorage.isLoggedIn()) {
      router.push("/login");
      return;
    }
    if (meetingId) {
      loadMeetingData();
    }
  }, [meetingId, router]);

  async function loadMeetingData() {
    setLoading(true);
    setError("");
    try {
      const [detail, recData, speakersData, agentData] = await Promise.all([
        api.getMeeting(meetingId),
        api.getRecording(meetingId).catch(() => null),
        api.getSpeakers(meetingId).catch(() => []),
        api.getAgentStatus().catch(() => ({ state: "idle" })),
      ]);

      setMeeting(detail);
      setRecording(recData);
      setSpeakers(speakersData);
      setAgentState(agentData.state || "idle");
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
      setSuccess(`Audio transcribed successfully (${result.segment_count || 0} segments).`);
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
      setError("Please upload an audio file or transcript first.");
      return;
    }

    setAnalyzing(true);
    setError("");
    setSuccess("");

    try {
      await api.analyzeMeeting(meetingId);
      setSuccess("Analysis complete. Summary, decisions, and action items updated.");
      const detail = await api.getMeeting(meetingId);
      setMeeting(detail);
      setActiveTab("summary");
    } catch (err: any) {
      setError(err?.message || "Analysis failed.");
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
          ? "Recording enabled with consent tracking."
          : "Recording disabled."
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
      setSuccess(`Speaker renamed to "${updated.display_name}".`);
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
        { sender: "ai", text: "Sorry, I encountered an issue retrieving the answer. Please try again." },
      ]);
    } finally {
      setChatLoading(false);
    }
  }

  // Block 3: Speak AI answer aloud with TTS
  async function handleSpeakText(text: string) {
    if (playingTTS) return;
    setPlayingTTS(true);

    try {
      // 1. Try browser SpeechSynthesis for instant natural voice
      if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.0;
        utterance.onend = () => setPlayingTTS(false);
        utterance.onerror = () => setPlayingTTS(false);
        window.speechSynthesis.speak(utterance);
        return;
      }

      // 2. Fallback to server TTS synthesis
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

  // Block 3: Live mic segment callback
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
      setSuccess("Action item added.");
    } catch (err: any) {
      setError(err?.message || "Failed to create task");
    } finally {
      setAddingTask(false);
    }
  }

  async function handleAgentToggle() {
    setAgentBusy(true);
    setError("");
    try {
      if (agentState === "idle" || agentState === "stopped") {
        await api.startAgent(meetingId, "simulated");
        setAgentState("listening");
        setSuccess("AI Agent connected to meeting.");
      } else {
        await api.stopAgent();
        setAgentState("stopped");
        setSuccess("AI Agent disconnected.");
      }
    } catch (err: any) {
      setError(err?.message || "Failed to update agent state");
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

  if (loading) {
    return (
      <div className="app-container" style={{ textAlign: "center", padding: "100px 0" }}>
        <div className="spinner" style={{ margin: "0 auto 16px" }}></div>
        <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>Loading meeting details...</p>
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
      {/* Breadcrumb */}
      <div style={{ marginBottom: 14 }}>
        <Link href="/meetings" style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          ← Meetings
        </Link>
      </div>

      {/* Header Panel */}
      <div
        className="glass-panel"
        style={{
          marginBottom: 16,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 16,
          padding: "20px 24px",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6, flexWrap: "wrap" }}>
            <h1 style={{ fontSize: 20 }}>{meeting.title}</h1>
            <span className="badge badge-indigo">{meeting.platform || "Direct"}</span>
            {meeting.transcript && <span className="badge badge-emerald">Transcribed</span>}
          </div>
          <p style={{ color: "var(--text-muted)", fontSize: 12 }}>
            Created: {meeting.created_at ? new Date(meeting.created_at).toLocaleString() : "Recently"}
          </p>
        </div>

        {/* Action Controls */}
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          {/* Recording Toggle */}
          <button
            onClick={handleToggleRecording}
            className={`btn btn-sm ${recording?.enabled ? "btn-danger" : "btn-secondary"}`}
            title="Recording consent toggle"
          >
            {recording?.enabled ? "Recording: ON" : "Record: OFF"}
          </button>

          {/* Upload Button */}
          <label className="btn btn-secondary btn-sm" style={{ cursor: uploading ? "wait" : "pointer" }}>
            {uploading ? (
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span className="spinner"></span>
                <span>Transcribing...</span>
              </span>
            ) : (
              <span>Upload Audio</span>
            )}
            <input
              type="file"
              accept="audio/*"
              hidden
              disabled={uploading}
              onChange={handleAudioUpload}
            />
          </label>

          {/* Analyze Button */}
          <button
            onClick={handleAnalyze}
            className="btn btn-primary btn-sm"
            disabled={analyzing || !meeting.transcript}
          >
            {analyzing ? (
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span className="spinner"></span>
                <span>Analyzing...</span>
              </span>
            ) : (
              <span>Analyze Meeting</span>
            )}
          </button>
        </div>
      </div>

      {/* Block 3: Live Microphone Stream Component */}
      <LiveRecorder
        meetingId={meetingId}
        onNewSegment={handleLiveSegment}
        onLiveActionCreated={handleLiveActionCreated}
      />

      {/* Alerts */}
      {error && <div className="alert-box alert-error">{error}</div>}
      {success && <div className="alert-box alert-success">{success}</div>}

      {/* Tabs */}
      <div className="tabs-nav">
        <button
          className={`tab-btn ${activeTab === "summary" ? "active" : ""}`}
          onClick={() => setActiveTab("summary")}
        >
          Summary
        </button>
        <button
          className={`tab-btn ${activeTab === "decisions" ? "active" : ""}`}
          onClick={() => setActiveTab("decisions")}
        >
          Decisions ({meeting.decisions?.length || 0})
        </button>
        <button
          className={`tab-btn ${activeTab === "tasks" ? "active" : ""}`}
          onClick={() => setActiveTab("tasks")}
        >
          Action Items ({meeting.action_items?.length || 0})
        </button>
        <button
          className={`tab-btn ${activeTab === "transcript" ? "active" : ""}`}
          onClick={() => setActiveTab("transcript")}
        >
          Transcript ({meeting.segments?.length || (meeting.transcript ? 1 : 0)})
        </button>
        <button
          className={`tab-btn ${activeTab === "chat" ? "active" : ""}`}
          onClick={() => setActiveTab("chat")}
        >
          AI Q&A Copilot
        </button>
        <button
          className={`tab-btn ${activeTab === "agent" ? "active" : ""}`}
          onClick={() => setActiveTab("agent")}
        >
          Agent
        </button>
      </div>

      {/* Panels */}
      <div className="glass-panel" style={{ minHeight: 380, padding: 24 }}>
        {/* SUMMARY TAB */}
        {activeTab === "summary" && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <h3 style={{ fontSize: 16 }}>Executive Summary</h3>
              {meeting.summary && (
                <span className="badge badge-cyan">
                  {meeting.summary.provider || "ollama"}
                </span>
              )}
            </div>

            {meeting.summary?.text ? (
              <div
                style={{
                  background: "var(--bg-input)",
                  padding: 18,
                  borderRadius: "var(--radius-sm)",
                  lineHeight: 1.6,
                  fontSize: 14,
                  whiteSpace: "pre-wrap",
                  border: "1px solid var(--border-subtle)",
                }}
              >
                {meeting.summary.text}
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "50px 20px", color: "var(--text-muted)" }}>
                <p style={{ marginBottom: 14, fontSize: 14 }}>
                  No summary generated yet.
                </p>
                {meeting.transcript ? (
                  <button onClick={handleAnalyze} className="btn btn-primary btn-sm" disabled={analyzing}>
                    Run Analysis
                  </button>
                ) : (
                  <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>
                    Use the Live Mic above or upload audio to generate transcript and summary.
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        {/* DECISIONS TAB */}
        {activeTab === "decisions" && (
          <div>
            <h3 style={{ fontSize: 16, marginBottom: 16 }}>Decisions</h3>
            {meeting.decisions && meeting.decisions.length > 0 ? (
              <div style={{ display: "grid", gap: 10 }}>
                {meeting.decisions.map((d, index) => (
                  <div
                    key={d.id || index}
                    style={{
                      background: "var(--bg-input)",
                      padding: "14px 16px",
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid var(--border-subtle)",
                      fontSize: 14,
                      lineHeight: 1.5,
                    }}
                  >
                    {d.text}
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "50px 20px", color: "var(--text-muted)" }}>
                <p style={{ fontSize: 14 }}>No decisions recorded yet.</p>
              </div>
            )}
          </div>
        )}

        {/* TASKS TAB */}
        {activeTab === "tasks" && (
          <div>
            <h3 style={{ fontSize: 16, marginBottom: 16 }}>Action Items</h3>

            {/* Add task form */}
            <form
              onSubmit={handleCreateTask}
              style={{
                display: "grid",
                gridTemplateColumns: "2fr 1fr 1fr auto",
                gap: 8,
                marginBottom: 20,
                background: "var(--bg-input)",
                padding: 12,
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border-subtle)",
              }}
            >
              <input
                type="text"
                className="form-input"
                placeholder="Task description..."
                value={newTaskText}
                onChange={(e) => setNewTaskText(e.target.value)}
                required
              />
              <input
                type="text"
                className="form-input"
                placeholder="Assignee (optional)"
                value={newTaskAssignee}
                onChange={(e) => setNewTaskAssignee(e.target.value)}
              />
              <input
                type="text"
                className="form-input"
                placeholder="Deadline (optional)"
                value={newTaskDeadline}
                onChange={(e) => setNewTaskDeadline(e.target.value)}
              />
              <button type="submit" className="btn btn-primary btn-sm" disabled={addingTask || !newTaskText.trim()}>
                {addingTask ? "Adding..." : "Add"}
              </button>
            </form>

            {/* Tasks list */}
            {meeting.action_items && meeting.action_items.length > 0 ? (
              <div style={{ display: "grid", gap: 8 }}>
                {meeting.action_items.map((item) => (
                  <div
                    key={item.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 14,
                      background: "var(--bg-input)",
                      padding: "12px 16px",
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid var(--border-subtle)",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 12, flex: 1 }}>
                      <input
                        type="checkbox"
                        checked={item.status === "done"}
                        onChange={() => handleToggleTaskStatus(item.id, item.status)}
                        style={{
                          width: 16,
                          height: 16,
                          cursor: "pointer",
                        }}
                      />
                      <div>
                        <p
                          style={{
                            fontSize: 14,
                            marginBottom: 2,
                            textDecoration: item.status === "done" ? "line-through" : "none",
                            color: item.status === "done" ? "var(--text-muted)" : "var(--text-primary)",
                          }}
                        >
                          {item.task}
                        </p>
                        <div style={{ display: "flex", gap: 10, fontSize: 12, color: "var(--text-muted)" }}>
                          {item.assignee && <span>Assignee: {item.assignee}</span>}
                          {item.deadline && <span>Due: {item.deadline}</span>}
                        </div>
                      </div>
                    </div>

                    <button
                      onClick={() => handleDeleteTask(item.id)}
                      className="btn btn-secondary btn-sm"
                      style={{ padding: "3px 8px", fontSize: 12 }}
                      title="Delete task"
                    >
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)" }}>
                <p style={{ fontSize: 14 }}>No action items recorded.</p>
              </div>
            )}
          </div>
        )}

        {/* TRANSCRIPT TAB (with Speaker Diarization Mapping & Search) */}
        {activeTab === "transcript" && (
          <div>
            {/* Speaker identification bar */}
            {speakers.length > 0 && (
              <div
                style={{
                  background: "var(--bg-input)",
                  padding: "12px 16px",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border-subtle)",
                  marginBottom: 16,
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  flexWrap: "wrap",
                }}
              >
                <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text-secondary)" }}>
                  Identified Speakers:
                </span>
                {speakers.map((spk) => (
                  <div key={spk.id} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    {editingSpeakerId === spk.id ? (
                      <div style={{ display: "flex", gap: 4 }}>
                        <input
                          type="text"
                          className="form-input"
                          style={{ padding: "3px 8px", fontSize: 12, width: 120 }}
                          value={editSpeakerName}
                          onChange={(e) => setEditSpeakerName(e.target.value)}
                          placeholder="Name..."
                          autoFocus
                        />
                        <button
                          onClick={() => handleRenameSpeaker(spk.id)}
                          className="btn btn-primary btn-sm"
                          style={{ padding: "2px 8px", fontSize: 11 }}
                          disabled={updatingSpeaker}
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setEditingSpeakerId(null)}
                          className="btn btn-secondary btn-sm"
                          style={{ padding: "2px 6px", fontSize: 11 }}
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
                        style={{ cursor: "pointer", border: "1px solid var(--border-card-hover)" }}
                        title="Click to rename speaker"
                      >
                        <span>{spk.display_name || spk.speaker_label}</span>
                        <span style={{ opacity: 0.6, fontSize: 10 }}>✎</span>
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
                marginBottom: 16,
                flexWrap: "wrap",
                gap: 10,
              }}
            >
              <h3 style={{ fontSize: 16 }}>Transcript Timeline</h3>

              <input
                type="text"
                className="form-input"
                placeholder="Search transcript..."
                style={{ width: 200, padding: "6px 10px", fontSize: 13 }}
                value={transcriptSearch}
                onChange={(e) => setTranscriptSearch(e.target.value)}
              />
            </div>

            {meeting.segments && meeting.segments.length > 0 ? (
              <div
                style={{
                  display: "grid",
                  gap: 10,
                  maxHeight: 480,
                  overflowY: "auto",
                  paddingRight: 4,
                }}
              >
                {filteredSegments.map((seg, idx) => (
                  <div
                    key={seg.id || idx}
                    style={{
                      background: "var(--bg-input)",
                      padding: "12px 14px",
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
                        marginBottom: 4,
                      }}
                    >
                      <span className="badge badge-cyan" style={{ fontSize: 11 }}>
                        {getSpeakerDisplayName(seg.speaker_label)}
                      </span>
                      <span>
                        [{formatTime(seg.start_time)} - {formatTime(seg.end_time)}]
                      </span>
                    </div>
                    <p style={{ fontSize: 14, lineHeight: 1.5 }}>{seg.text}</p>
                  </div>
                ))}
              </div>
            ) : meeting.transcript ? (
              <div
                style={{
                  background: "var(--bg-input)",
                  padding: 16,
                  borderRadius: "var(--radius-sm)",
                  lineHeight: 1.6,
                  fontSize: 14,
                  whiteSpace: "pre-wrap",
                }}
              >
                {meeting.transcript}
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "50px 20px", color: "var(--text-muted)" }}>
                <p style={{ marginBottom: 14, fontSize: 14 }}>No transcript available for this meeting.</p>
                <label className="btn btn-secondary btn-sm" style={{ cursor: "pointer" }}>
                  Upload Audio
                  <input type="file" accept="audio/*" hidden onChange={handleAudioUpload} />
                </label>
              </div>
            )}
          </div>
        )}

        {/* AI MEETING CHAT TAB (Block 2) with TTS Voice (Block 3) */}
        {activeTab === "chat" && (
          <div>
            <div style={{ marginBottom: 16 }}>
              <h3 style={{ fontSize: 16, marginBottom: 4 }}>Meeting Q&A Copilot</h3>
              <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
                Ask any question grounded directly in this meeting's transcript, decisions, and action items.
              </p>
            </div>

            {/* Quick Suggestions */}
            <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
              <button
                type="button"
                onClick={() => handleSendChatMessage("What are the key decisions made in this meeting?")}
                className="btn btn-secondary btn-sm"
                style={{ fontSize: 12 }}
                disabled={chatLoading}
              >
                Key Decisions?
              </button>
              <button
                type="button"
                onClick={() => handleSendChatMessage("Who was assigned tasks and what are their deadlines?")}
                className="btn btn-secondary btn-sm"
                style={{ fontSize: 12 }}
                disabled={chatLoading}
              >
                Assigned Tasks?
              </button>
              <button
                type="button"
                onClick={() => handleSendChatMessage("Summarize the meeting in 3 bullet points.")}
                className="btn btn-secondary btn-sm"
                style={{ fontSize: 12 }}
                disabled={chatLoading}
              >
                3-Bullet Summary
              </button>
            </div>

            {/* Chat Thread */}
            <div
              style={{
                background: "var(--bg-input)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
                padding: 16,
                minHeight: 220,
                maxHeight: 380,
                overflowY: "auto",
                display: "flex",
                flexDirection: "column",
                gap: 12,
                marginBottom: 16,
              }}
            >
              {chatMessages.length === 0 ? (
                <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)", fontSize: 13 }}>
                  Type a question below or click one of the suggestion chips above.
                </div>
              ) : (
                chatMessages.map((msg, idx) => (
                  <div
                    key={idx}
                    style={{
                      alignSelf: msg.sender === "user" ? "flex-end" : "flex-start",
                      maxWidth: "85%",
                      background: msg.sender === "user" ? "var(--accent-primary)" : "var(--bg-card)",
                      color: "#fff",
                      padding: "10px 14px",
                      borderRadius: "var(--radius-sm)",
                      border: msg.sender === "ai" ? "1px solid var(--border-card)" : "none",
                      fontSize: 14,
                      lineHeight: 1.5,
                    }}
                  >
                    <p style={{ whiteSpace: "pre-wrap" }}>{msg.text}</p>
                    
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8, gap: 10 }}>
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
                          style={{ padding: "2px 6px", fontSize: 11 }}
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
                    padding: "10px 14px",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--border-card)",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 13,
                    color: "var(--text-secondary)",
                  }}
                >
                  <span className="spinner"></span>
                  <span>Generating answer from meeting context...</span>
                </div>
              )}
            </div>

            {/* Input form */}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSendChatMessage();
              }}
              style={{ display: "flex", gap: 8 }}
            >
              <input
                type="text"
                className="form-input"
                placeholder="Ask about this meeting..."
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                disabled={chatLoading}
              />
              <button type="submit" className="btn btn-primary btn-sm" disabled={chatLoading || !chatInput.trim()}>
                Ask
              </button>
            </form>
          </div>
        )}

        {/* AGENT TAB */}
        {activeTab === "agent" && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
              <div>
                <h3 style={{ fontSize: 16, marginBottom: 4 }}>Assistant Agent Status</h3>
                <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
                  Simulated agent runtime for live meeting capture and assistance.
                </p>
              </div>

              <div>
                <span
                  className={`badge ${
                    agentState === "listening"
                      ? "badge-emerald"
                      : agentState === "stopped"
                      ? "badge-rose"
                      : "badge-amber"
                  }`}
                  style={{ textTransform: "uppercase" }}
                >
                  Status: {agentState}
                </span>
              </div>
            </div>

            <div
              style={{
                background: "var(--bg-input)",
                padding: 18,
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border-subtle)",
              }}
            >
              <div style={{ display: "flex", gap: 10 }}>
                <button
                  onClick={handleAgentToggle}
                  className={`btn btn-sm ${agentState === "listening" ? "btn-danger" : "btn-primary"}`}
                  disabled={agentBusy}
                >
                  {agentBusy
                    ? "Updating..."
                    : agentState === "listening"
                    ? "Stop Agent"
                    : "Start Agent"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
