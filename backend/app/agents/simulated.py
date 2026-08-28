"""In-memory simulated agent used before real meeting integration."""

from app.schemas.agent import AgentState


class SimulatedAgent:
    def __init__(self) -> None:
        self.state: AgentState = "idle"
        self.meeting_id: int | None = None

    def start(self, meeting_id: int | None = None) -> None:
        if self.state not in {"idle", "stopped"}:
            raise ValueError("Agent is already running.")
        self.meeting_id = meeting_id
        self.state = "joining"
        self.state = "listening"

    def stop(self) -> None:
        if self.state in {"idle", "stopped"}:
            self.state = "stopped"
            return
        self.state = "leaving"
        self.state = "stopped"
        self.meeting_id = None

    def status(self) -> tuple[AgentState, int | None]:
        return self.state, self.meeting_id
