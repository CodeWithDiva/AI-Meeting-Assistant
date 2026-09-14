"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Wraps the browser's built-in speech recognition (Chrome/Edge; silently
 * unsupported elsewhere — check `supported` before showing a mic button) so
 * any text input can also be filled by voice. Shared by the workspace-wide
 * ask panel and the in-meeting assistant test box, rather than duplicating
 * the same SpeechRecognition wiring in both.
 */
export function useVoiceInput(onFinal: (transcript: string) => void) {
  const [listening, setListening] = useState(false);
  const [supported, setSupported] = useState(false);
  const recognitionRef = useRef<any>(null);
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;

  useEffect(() => {
    setSupported(!!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition));
  }, []);

  function toggle(onInterim?: (transcript: string) => void) {
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    let latest = "";
    recognition.onresult = (event: any) => {
      let transcript = "";
      for (let i = 0; i < event.results.length; i++) transcript += event.results[i][0].transcript;
      latest = transcript;
      onInterim?.(transcript);
    };
    recognition.onerror = () => setListening(false);
    recognition.onend = () => {
      setListening(false);
      if (latest.trim()) onFinalRef.current(latest.trim());
    };

    recognitionRef.current = recognition;
    setListening(true);
    recognition.start();
  }

  return { listening, supported, toggle };
}
