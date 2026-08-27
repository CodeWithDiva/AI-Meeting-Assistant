"""FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(
    title="AI Meeting Assistant API",
    version="0.1.0",
    description="Backend API for the AI Meeting Assistant.",
)


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Return a lightweight service-health response."""
    return {"status": "ok"}
