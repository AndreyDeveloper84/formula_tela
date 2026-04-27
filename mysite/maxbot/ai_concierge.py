"""AIConcierge — оркестратор chat-pipeline (заменяет chat_rag для AI-помощника).

См. docs/plans/maxbot-phase2-native-booking.md §T06.
Базируется на Ayla/djangoproject/ai/application/services/chat_service.py.

Pipeline:
1. _resolve_conversation(bot_user) → Conversation (existing active OR new)
2. save Message(role=user)
3. _build_master_context() → Top-N мастеров + их услуги
4. _load_recent_messages(conv, limit=10) → история для LLM-context
5. render_system_prompt(bot_user, context) → system message
6. call OpenAI с TOOL_DEFINITIONS
7. if tool_call → dispatch_tool_call() → ToolResult
8. save Message(role=assistant, action_type, action_data, tokens, latency)
9. return ChatResponseDTO (conversation_id, action_type, action_data, content)

Telemetry: Message.tokens_in/out + latency_ms сохраняются для observability.

TODO Phase 2.3 T06:
- Реализовать send_message() pipeline по схеме выше
- _resolve_conversation: получить is_active=True conversation для bot_user, или создать
- _save_message(conv, role, content, **kwargs) async ORM
- _load_recent_messages(conv, limit) async ORM с порядком created_at ASC
- _compose(system, history, user_text) → list[dict] для openai
- _call_openai(messages, tools=TOOL_DEFINITIONS) → ChatCompletion
- ChatResponseDTO dataclass
- Integration-тесты test_ai_concierge.py на 5 интентов
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class ChatResponseDTO:
    """Что AIConcierge возвращает caller'у (handler'у в ai_assistant.py)."""

    conversation_id: UUID
    content: str
    action_type: str | None
    action_data: dict[str, Any] | None
