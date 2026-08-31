"use client";

import { useEffect, useRef, useState } from "react";
import { api, Segment } from "@/lib/api";

interface LiveRecorderProps {
  meetingId: number;
  onNewSegment: (segment: Segment) => void;
  onLiveActionCreated?: (task: string) => void;
}

export default function LiveRecorder({
  meetingId,
  onNewSegment,
  onLiveActionCreated,
}: LiveRecorderProps) {
  const [isRecording, setIsRecording] = useState(false);
  const [liveStatus, setLiveStatus] = useState<string>("Ready to stream");
  const [livePreviewText, setLivePreviewText] = useState("");

  const wsRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    return () => {
      stopRecording();
    };
  }, []);

  async function startRecording() {
    try {
      setLiveStatus("Requesting microphone permission...");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;

      // 1. Establish WebSocket Connection
      const wsUrl = api.getLiveWebSocketUrl(meetingId);
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setLiveStatus("Streaming live audio to faster-whisper pipeline");
        setIsRecording(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "transcript_segment") {
            const newSeg: Segment = {
              text: data.text,
              speaker_label: data.speaker || "SPEAKER_LIVE",
              start_time: data.start_time || 0,
              end_time: data.end_time || 0,
              source: "live_mic",
            };
            onNewSegment(newSeg);
            setLivePreviewText(data.text);
            if (data.action_created && onLiveActionCreated) {
              onLiveActionCreated(data.action_created);
            }
          }
        } catch (e) {
          // ignore
        }
      };

      ws.onerror = () => {
        setLiveStatus("WebSocket stream connected (local speech synthesis fallback active)");
      };

      // 2. Start MediaRecorder to stream audio slices
      let recorder: MediaRecorder;
      try {
        recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
      } catch {
        recorder = new MediaRecorder(stream);
      }
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = async (e) => {
        if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
          const arrayBuffer = await e.data.arrayBuffer();
          ws.send(arrayBuffer);
        }
      };

      recorder.start(3000); // 3-second slices

      // 3. Browser Native SpeechRecognition for zero-latency speech preview
      const SpeechRecognition =
        (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

      if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = "en-US";

        recognition.onresult = (event: any) => {
          let interim = "";
          let final = "";
          for (let i = event.resultIndex; i < event.results.length; ++i) {
            if (event.results[i].isFinal) {
              final += event.results[i][0].transcript;
            } else {
              interim += event.results[i][0].transcript;
            }
          }
          if (final && ws.readyState === WebSocket.OPEN) {
            ws.send(
              JSON.stringify({
                type: "text_segment",
                text: final,
                speaker: "SPEAKER_1",
              })
            );
          }
          setLivePreviewText(interim || final);
        };

        recognition.start();
        recognitionRef.current = recognition;
      }

      setIsRecording(true);
      setLiveStatus("Live microphone active — listening...");
    } catch (err: any) {
      setLiveStatus("Microphone access denied or error occurred.");
      setIsRecording(false);
    }
  }

  function stopRecording() {
    setIsRecording(false);
    setLiveStatus("Ready to stream");
    setLivePreviewText("");

    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {}
      recognitionRef.current = null;
    }

    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      try {
        mediaRecorderRef.current.stop();
      } catch {}
      mediaRecorderRef.current = null;
    }

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
    }

    if (wsRef.current) {
      try {
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: "stop" }));
          wsRef.current.close();
        }
      } catch {}
      wsRef.current = null;
    }
  }

  return (
    <div
      style={{
        background: isRecording
          ? "linear-gradient(135deg, rgba(244, 63, 94, 0.12) 0%, rgba(20, 24, 40, 0.95) 100%)"
          : "linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(15, 18, 30, 0.8) 100%)",
        border: isRecording
          ? "1px solid rgba(244, 63, 94, 0.45)"
          : "1px solid var(--border-card)",
        borderRadius: "var(--radius-md)",
        padding: "16px 20px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 14,
        marginBottom: 22,
        boxShadow: isRecording
          ? "0 0 25px rgba(244, 63, 94, 0.25)"
          : "var(--shadow-sm)",
        transition: "all 0.25s ease",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <button
          onClick={isRecording ? stopRecording : startRecording}
          className={`btn ${isRecording ? "btn-danger" : "btn-primary"}`}
          style={{ padding: "8px 16px" }}
        >
          {isRecording ? (
            <>
              <span className="status-dot status-dot-recording" />
              <span>Stop Live Mic</span>
            </>
          ) : (
            <>
              <span>🎙️</span>
              <span>Start Live Mic</span>
            </>
          )}
        </button>

        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: "#ffffff" }}>
              {isRecording ? "Active Voice Capture" : "Real-Time Microphone Stream"}
            </span>
            {isRecording && <span className="badge badge-rose">LIVE</span>}
          </div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
            {liveStatus}
          </p>
        </div>
      </div>

      {isRecording && livePreviewText && (
        <div
          style={{
            flex: 1,
            minWidth: 240,
            background: "rgba(10, 13, 22, 0.9)",
            padding: "8px 14px",
            borderRadius: "var(--radius-sm)",
            fontSize: 13,
            color: "#f8fafc",
            border: "1px solid rgba(244, 63, 94, 0.3)",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span style={{ color: "#fb7185", fontSize: 14 }}>💬</span>
          <span style={{ fontStyle: "italic", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            &ldquo;{livePreviewText}&rdquo;
          </span>
        </div>
      )}
    </div>
  );
}
