"""Conversation history, keyed by conversation (LangGraph thread) id.

CONVERSATION_BACKEND selects where it lives:
  memory (default) - a dict in this process; fine for one local server
  dynamodb         - Amazon DynamoDB; needed on Lambda, where each request can
                     land on a different, short-lived instance
"""

import json
import os
import time
from functools import lru_cache
from typing import Protocol

from langchain_core.messages import BaseMessage, HumanMessage, messages_from_dict, messages_to_dict

# DynamoDB items are limited to 400 KB; keep history comfortably below that.
MAX_HISTORY_BYTES = 300_000
TTL_SECONDS = 7 * 24 * 3600


class ConversationStore(Protocol):
    def load(self, thread_id: str) -> list[BaseMessage]: ...
    def save(self, thread_id: str, messages: list[BaseMessage]) -> None: ...
    def delete(self, thread_id: str) -> None: ...


def _serialize(messages: list[BaseMessage]) -> str:
    """JSON-encode, dropping the oldest turns if needed to fit the size limit.

    Trimming only ever cuts right before a user message, so a tool call is never
    separated from its result.
    """
    while True:
        data = json.dumps(messages_to_dict(messages))
        if len(data.encode()) <= MAX_HISTORY_BYTES:
            return data
        starts = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and i > 0]
        if not starts:
            return data
        messages = messages[starts[0]:]


class MemoryConversationStore:
    def __init__(self):
        self._threads: dict[str, list[BaseMessage]] = {}

    def load(self, thread_id):
        return list(self._threads.get(thread_id, []))

    def save(self, thread_id, messages):
        self._threads[thread_id] = list(messages)

    def delete(self, thread_id):
        self._threads.pop(thread_id, None)


class DynamoConversationStore:
    def __init__(self, table_name: str):
        import boto3

        self._table = boto3.resource("dynamodb").Table(table_name)

    def load(self, thread_id):
        item = self._table.get_item(Key={"thread_id": thread_id}).get("Item")
        return messages_from_dict(json.loads(item["messages"])) if item else []

    def save(self, thread_id, messages):
        self._table.put_item(Item={
            "thread_id": thread_id,
            "messages": _serialize(messages),
            "expires_at": int(time.time()) + TTL_SECONDS,  # DynamoDB TTL removes stale chats
        })

    def delete(self, thread_id):
        self._table.delete_item(Key={"thread_id": thread_id})


@lru_cache
def get_conversation_store() -> ConversationStore:
    if os.getenv("CONVERSATION_BACKEND", "memory") == "dynamodb":
        return DynamoConversationStore(os.environ["CONVERSATIONS_TABLE"])
    return MemoryConversationStore()
