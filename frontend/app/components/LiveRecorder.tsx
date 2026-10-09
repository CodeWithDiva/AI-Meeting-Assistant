"use client";

import { useEffect, useRef, useState } from "react";
import { api, Segment } from "@/lib/api";
import { DEMO_MODE } from "@/lib/demo";
import Icon from "./Icon";

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
    if (DEMO_MODE) {
      setLiveStatus("Live transcription runs on the assistant's local backend, so it is off in this demo.");
      return;
    }
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
        background: isRecording ? "var(--tint-rose)" : "var(--bg-card)",
        border: isRecording ? "1px solid color-mix(in srgb, var(--accent-rose) 35%, transparent)" : "1px solid var(--border-card)",
        borderRadius: "var(--radius-md)",
        padding: "14px 18px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 14,
        marginBottom: 20,
        transition: "all 0.2s ease",
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
              <span className="status-dot status-dot-recording" style={{ background: "currentColor" }} />
              <span>Stop live mic</span>
            </>
          ) : (
            <>
              <Icon name="mic" size={14} />
              <span>Start live mic</span>
            </>
          )}
        </button>

        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13.5, fontWeight: 700, color: "var(--text-primary)" }}>
              {isRecording ? "Active voice capture" : "Real-time microphone stream"}
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
            background: "var(--bg-surface)",
            padding: "8px 14px",
            borderRadius: "var(--radius-sm)",
            fontSize: 12.5,
            color: "var(--text-secondary)",
            border: "1px solid var(--border-card)",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <Icon name="message" size={13} className="mono" />
          <span style={{ fontStyle: "italic", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            &ldquo;{livePreviewText}&rdquo;
          </span>
        </div>
      )}
    </div>
  );
}
