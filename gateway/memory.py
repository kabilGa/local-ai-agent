"""
Conversation Memory
===================
Keeps a short history of each conversation so the agent has context
and doesn't "forget" the previous messages.

How it works (simple version):
  - each browser/chat session has a unique session_id
  - we store the recent messages for that session in a dictionary
  - when a new message comes in, we send the recent history WITH it
    so the model can see what was said before

This is in-memory: it resets when the gateway restarts. That's fine for
a POC. (A real version would use a database so it survives restarts.)
"""

from collections import defaultdict, deque

# How many past messages to remember per session.
# Too many = slow + confuses small models. 8 is a good balance.
MAX_HISTORY = 8

# session_id -> deque of {"role": "user"/"assistant", "content": "..."}
_store: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY))


def add_message(session_id: str, role: str, content: str) -> None:
    """Record a message (role is 'user' or 'assistant') for this session."""
    if not session_id:
        return
    _store[session_id].append({"role": role, "content": content})


def get_history(session_id: str) -> list[dict]:
    """Return the recent messages for this session, oldest first."""
    if not session_id or session_id not in _store:
        return []
    return list(_store[session_id])


def clear_session(session_id: str) -> None:
    """Forget a conversation (e.g. when the user clicks 'new chat')."""
    _store.pop(session_id, None)


def build_prompt_with_history(session_id: str, new_prompt: str) -> str:
    """
    Combine the conversation history with the new prompt into ONE text block
    that we send to the model. This is what gives the model 'memory'.

    The format looks like a transcript:
        User: hi
        Assistant: hello, how can I help?
        User: what did I just say?
    """
    history = get_history(session_id)
    if not history:
        return new_prompt  # first message, nothing to add

    lines = []
    for msg in history:
        speaker = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{speaker}: {msg['content']}")
    lines.append(f"User: {new_prompt}")
    lines.append("Assistant:")  # cue the model to answer next

    transcript = "\n".join(lines)
    # A short instruction helps the model use the history correctly.
    return (
        "Continue this conversation. Use the earlier messages for context.\n\n"
        + transcript
    )
