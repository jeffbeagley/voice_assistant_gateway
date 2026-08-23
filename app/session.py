"""In-memory session/conversation state, with barge-in support.

Each websocket connection owns exactly one ConversationSession. State is not
shared across gateway replicas (see README for the Redis upgrade path).
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class ConversationSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    history: list[dict[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)
    last_active: float = field(default_factory=time.monotonic)

    # Tracks the in-flight "process this utterance" task so a new utterance
    # (barge-in) can cancel it, and cancel/stop any TTS audio being streamed.
    active_task: asyncio.Task | None = None

    def touch(self) -> None:
        self.last_active = time.monotonic()

    def append(self, role: str, content: str, max_turns: int) -> None:
        self.history.append({"role": role, "content": content})
        # Keep only the last N user/assistant turn pairs to bound prompt size.
        max_messages = max_turns * 2
        if len(self.history) > max_messages:
            self.history = self.history[-max_messages:]

    async def cancel_active(self) -> None:
        """Cancel any in-flight pipeline task (used for barge-in)."""
        task = self.active_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self.active_task = None


class SessionManager:
    def __init__(self, idle_timeout_seconds: float):
        self._sessions: dict[str, ConversationSession] = {}
        self._idle_timeout = idle_timeout_seconds

    def create(self) -> ConversationSession:
        session = ConversationSession()
        self._sessions[session.session_id] = session
        return session

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def sweep_idle(self) -> None:
        now = time.monotonic()
        stale = [
            sid
            for sid, s in self._sessions.items()
            if now - s.last_active > self._idle_timeout
        ]
        for sid in stale:
            self._sessions.pop(sid, None)
