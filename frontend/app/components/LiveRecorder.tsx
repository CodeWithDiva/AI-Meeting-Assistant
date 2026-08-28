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
  const [liveStatus, setLiveStatus] = useState<string>("Ready");
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
      setLiveStatus("Connecting microphone...");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;

      // 1. Establish WebSocket Connection
      const wsUrl = api.getLiveWebSocketUrl(meetingId);
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setLiveStatus("Live — Streaming Audio");
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
        setLiveStatus("WebSocket error, falling back to local recognition...");
      };

      // 2. Start MediaRecorder to stream chunks
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

      // 3. Browser Native SpeechRecognition for instant zero-latency speech preview
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
                speaker: "YOU (LIVE)",
              })
            );
          }
          setLivePreviewText(interim || final);
        };

        recognition.start();
        recognitionRef.current = recognition;
      }

      setIsRecording(true);
      setLiveStatus("Recording live...");
    } catch (err: any) {
      setLiveStatus("Microphone access denied or failed.");
      setIsRecording(false);
    }
  }

  function stopRecording() {
    setIsRecording(false);
    setLiveStatus("Stopped");
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
        background: isRecording ? "rgba(239, 68, 68, 0.08)" : "var(--bg-input)",
        border: isRecording ? "1px solid rgba(239, 68, 68, 0.4)" : "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-sm)",
        padding: "14px 18px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 12,
        marginBottom: 18,
        transition: "all 0.2s ease",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button
          onClick={isRecording ? stopRecording : startRecording}
          className={`btn btn-sm ${isRecording ? "btn-danger" : "btn-primary"}`}
          style={{ display: "flex", alignItems: "center", gap: 6 }}
        >
          {isRecording ? (
            <>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  backgroundColor: "#fff",
                  display: "inline-block",
                  animation: "pulse 1s infinite",
                }}
              />
              <span>Stop Mic</span>
            </>
          ) : (
            <>
              <span style={{ fontSize: 12 }}>🔴</span>
              <span>Start Live Mic</span>
            </>
          )}
        </button>

        <div>
          <span style={{ fontSize: 13, fontWeight: 500 }}>
            {isRecording ? "Listening to Microphone..." : "Live Microphone Stream"}
          </span>
          <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            {liveStatus}
          </p>
        </div>
      </div>

      {isRecording && livePreviewText && (
        <div
          style={{
            flex: 1,
            minWidth: 200,
            background: "var(--bg-card)",
            padding: "6px 12px",
            borderRadius: "var(--radius-sm)",
            fontSize: 13,
            color: "var(--text-primary)",
            border: "1px solid var(--border-card)",
            fontStyle: "italic",
          }}
        >
          &ldquo;{livePreviewText}&rdquo;
        </div>
      )}
    </div>
  );
}
