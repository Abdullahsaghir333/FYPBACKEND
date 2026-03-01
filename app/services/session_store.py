from typing import Dict

from app.models import SessionState


_SESSIONS: Dict[str, SessionState] = {}


def save_session(state: SessionState) -> None:
    _SESSIONS[state.id] = state


def get_session(session_id: str) -> SessionState | None:
    return _SESSIONS.get(session_id)


