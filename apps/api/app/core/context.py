"""Request-scoped context values (currently the audit actor)."""

from contextvars import ContextVar

current_actor: ContextVar[str] = ContextVar("current_actor", default="system")


def set_actor(actor: str) -> None:
    current_actor.set(actor)


def get_actor() -> str:
    return current_actor.get()
