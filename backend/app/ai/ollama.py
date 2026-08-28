"""Ollama-backed meeting analysis."""

import os
from typing import Any

import httpx


async def analyze_with_ollama(transcript: str) -> dict[str, Any]:
    """Ask a local Ollama model for structured meeting notes."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    prompt = (
        "Analyze this meeting transcript. Return JSON only with exactly these keys: "
        "summary (string), decisions (array of strings), action_items (array of objects "
        "with assignee, task, deadline string or null). Transcript:\n\n" + transcript
    )

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            response = await client.post(
                f"{base_url}/api/generate",
                json={"model": model, "prompt": prompt, "format": "json", "stream": False},
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError("Ollama is unavailable or returned an error.") from error

    result = response.json().get("response")
    if not isinstance(result, str):
        raise RuntimeError("Ollama returned an invalid analysis response.")

    import json

    parsed = json.loads(result)
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama returned a non-object analysis response.")
    return parsed
