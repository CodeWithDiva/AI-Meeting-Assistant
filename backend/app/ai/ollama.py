"""Ollama-backed meeting analysis — v3 improved prompt."""

import json
import os
from typing import Any

import httpx


async def analyze_with_ollama(transcript: str) -> dict[str, Any]:
    """Ask a local Ollama model for structured meeting notes."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    prompt = (
        "You are an expert meeting analyst. Analyze this meeting transcript carefully.\n"
        "Return ONLY valid JSON with exactly these keys:\n"
        '  "summary": (string) a clear, concise summary of the meeting\n'
        '  "decisions": (array of strings) key decisions made during the meeting\n'
        '  "action_items": (array of objects) each with:\n'
        '    "assignee": (string) who must do the task\n'
        '    "assigned_by": (string or null) who assigned the task\n'
        '    "task": (string) what needs to be done\n'
        '    "deadline": (string or null) when it is due\n\n'
        "If no decisions or action items were found, return empty arrays.\n\n"
        "Transcript:\n\n" + transcript
    )

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            response = await client.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError("Ollama is unavailable or returned an error.") from error

    result = response.json().get("response")
    if not isinstance(result, str):
        raise RuntimeError("Ollama returned an invalid analysis response.")

    parsed = json.loads(result)
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama returned a non-object analysis response.")
    return parsed
