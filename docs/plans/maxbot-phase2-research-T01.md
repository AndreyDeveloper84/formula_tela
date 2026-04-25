# T-01 Research Spike: MCP SDK + OpenAI tool-use + Chroma

**Date:** 2026-04-25
**Goal:** зафиксировать точные API трёх библиотек чтобы T-02..T-13 шли по cargo.

---

## 1. MCP Python SDK

| Параметр | Значение |
|---|---|
| pip | `pip install "mcp[cli]"` (`uv add "mcp[cli]"` если uv) |
| Версия (2026-04) | 2026.1.0+ |
| Python | >=3.10 |
| FastMCP | wrapper включён в основной пакет (`mcp.server.fastmcp.FastMCP`) |

### 1.1 Минимальный server (stdio)

```python
# services/formulatela_mcp/src/formulatela_mcp/main.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("formulatela-mcp")

@mcp.tool()
def search_faq(query: str, k: int = 3) -> list[dict]:
    """Найти top-k FAQ-статей по семантической близости к query."""
    # ORM + embeddings → list of {"question": ..., "answer": ..., "score": ...}
    return [...]

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

**Ключевое:**
- Type hints → автоматический JSON Schema для tool arguments (`query: str, k: int = 3` → `{"type":"object","properties":{"query":{"type":"string"},"k":{"type":"integer","default":3}}}`)
- Описание из docstring → `tool.description`
- Поддержка sync **и** async (можно `async def`)
- Pydantic-модель в аргументе → автоматический schema из её полей
- `mcp.run(transport="stdio")` стандартный для subprocess-клиентов

### 1.2 Минимальный client (stdio)

```python
# mysite/maxbot/handlers/ai_assistant.py — фрагмент
import asyncio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def query_mcp_for_faq(query: str):
    server_params = StdioServerParameters(
        command="/home/taximeter/mysite/formula_tela/.venv312/bin/python",
        args=["-m", "formulatela_mcp.main"],
        env={"DJANGO_SETTINGS_MODULE": "mysite.settings", **os.environ},
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_resp = await session.list_tools()  # tools_resp.tools — list[Tool]
            result = await session.call_tool("search_faq", {"query": query, "k": 3})
            return result.content[0].text  # или structuredContent для JSON
```

**Важные нюансы для нашего деплоя:**
- `command` — абсолютный путь к python из `.venv312` чтобы у subprocess был maxapi/django/chromadb
- `args` — `["-m", "formulatela_mcp.main"]` или путь к main.py
- `env` — unix env, нужно прокинуть `DJANGO_SETTINGS_MODULE` + `OPENAI_API_KEY` + `DB_*` — иначе subprocess упадёт на Django setup
- Каждый `stdio_client(...)` спавнит **новый** subprocess. Для частых вызовов из maxbot — держать **persistent** session (создать `ClientSession` один раз при старте dispatcher'а, переиспользовать)

### 1.3 Структура ответа `call_tool()`

```python
result = await session.call_tool("search_faq", {"query": "..."})
# result.content       — list[TextContent | ImageContent | ...]
# result.content[0].text — для FastMCP по умолчанию JSON-string возврата
# result.structuredContent — dict (если tool возвращает Pydantic/TypedDict)
```

**Гочча:** FastMCP сериализует return value в JSON-строку → `content[0].text` это `'[{"question":"..."},...]'`. Чтобы в handler'е получить list — `json.loads(result.content[0].text)`.

---

## 2. OpenAI tool-use (function calling)

| Параметр | Значение |
|---|---|
| pip | `pip install openai` (≥1.50 на 2026-04, у нас 1.99.9 в requirements) |
| Models с tool-use | `gpt-4o-mini`, `gpt-4o`, `gpt-4-turbo` и др. |
| Async client | `AsyncOpenAI` (тот же интерфейс) |

### 2.1 Tool schema формат

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "search_faq",
            "description": "Найти top-k FAQ-статей по запросу клиента",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Текст вопроса клиента"},
                    "k": {"type": "integer", "default": 3, "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
        },
    },
]
```

**Bridge MCP → OpenAI:** структуры **совместимы** — оба используют JSON Schema. Конвертер ~10 строк:
```python
def mcp_tools_to_openai(mcp_tools_resp):
    return [
        {"type": "function", "function": {
            "name": t.name,
            "description": t.description or "",
            "parameters": t.inputSchema or {"type": "object", "properties": {}},
        }}
        for t in mcp_tools_resp.tools
    ]
```

### 2.2 Loop pattern

```python
from openai import AsyncOpenAI
import json

client = AsyncOpenAI()  # читает OPENAI_API_KEY из env
messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": user_text},
]

for _ in range(5):  # max 5 tool-iterations (защита от бесконечного цикла)
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        tools=tools,
    )
    msg = resp.choices[0].message
    if not msg.tool_calls:
        return msg.content  # финальный ответ

    # 1. Добавляем assistant-message с tool_calls
    messages.append({"role": "assistant", "content": msg.content or "",
                     "tool_calls": msg.tool_calls})

    # 2. Выполняем каждый tool через MCP
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments)
        result = await mcp_session.call_tool(tc.function.name, args)
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": result.content[0].text,  # JSON-string
        })

# Если сюда долетели — модель не остановилась за 5 итераций. Fallback.
return "Не получилось разобраться. Передаю менеджеру."
```

**Важно:**
- `openai-python` **не имеет** прямой интеграции с MCP — конвертируем tools руками (~10 строк выше)
- `tool_calls` = `None` если model не вызвал tool (= финальный ответ)
- `arguments` это **JSON-string**, обязательно `json.loads`
- `tool_call_id` обязателен в tool-message чтобы model связал ответ с запросом
- Защита от бесконечной петли — макс. N итераций (наш case: 5)

### 2.3 Прокси для OpenAI

В РФ `api.openai.com` тоже заблокирован. Существующий `agents/agents/__init__.py::get_openai_client()` уже умеет читать `OPENAI_PROXY` — **переиспользуем** вместо `AsyncOpenAI()` напрямую (есть факт в CLAUDE.md). Проверю в T-06 как get_openai_client работает с async.

---

## 3. Chroma (vector DB для FAQ embeddings)

| Параметр | Значение |
|---|---|
| pip | `pip install chromadb` (~50MB) |
| Persistence | filesystem (`chromadb.PersistentClient(path="...")`) |
| Embedding | автоматически вычисляется при `add()` если задан embedding_function |

### 3.1 OpenAI embedding function

```python
import chromadb
from chromadb.utils import embedding_functions

openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=os.environ["OPENAI_API_KEY"],
    model_name="text-embedding-3-small",  # дёшево, ~$0.02/1M tokens
)

client = chromadb.PersistentClient(path="/var/lib/formulatela-mcp/chroma")

collection = client.get_or_create_collection(
    name="help_articles",
    embedding_function=openai_ef,
    metadata={"hnsw:space": "cosine"},  # cosine similarity
)
```

### 3.2 Index + query

```python
# Reindex — стираем старые и заливаем все active HelpArticle
client.delete_collection("help_articles")
collection = client.get_or_create_collection("help_articles", embedding_function=openai_ef, ...)

articles = HelpArticle.objects.active()
collection.add(
    documents=[f"{a.question}\n\n{a.answer}" for a in articles],  # текст на эмбединг
    metadatas=[{"id": a.id, "question": a.question} for a in articles],
    ids=[str(a.id) for a in articles],
)

# Query
result = collection.query(query_texts=["как записаться?"], n_results=3)
# result.keys: ids, distances, documents, metadatas, embeddings
# distances[0] — list[float], для cosine ниже = ближе (0..2 диапазон, не "similarity")
# similarity = 1 - distance
```

**Гочча:** Chroma возвращает **distances** (cosine distance), НЕ similarity. Чтобы порог «релевантно если ≥ 0.7» — конвертить: `similarity = 1 - distance`.

### 3.3 Прокси для embedding API

Так же через `OPENAI_PROXY`. `OpenAIEmbeddingFunction` сам не знает про прокси — нужно либо передать ему собственный `httpx_client` с прокси, либо использовать `openai.AsyncOpenAI(http_client=...)` и собственный embedding-wrapper. **Решу в T-04** при реализации `chroma_backend.py`.

---

## 4. Чего research не покрыл (TBD)

1. **Persistent MCP-сессия в maxbot** — нужно ли держать одну сессию на весь процесс или открывать на каждый запрос? Subprocess spawn — это ~500ms overhead, для интерактивного UX неприемлемо. План: один глобальный `ClientSession` создаётся при старте dispatcher'а в `build_dispatcher`, переиспользуется (T-06).
2. **Прокси для OpenAI embedding в Chroma** — кастомный embedding function с прокси-aware httpx (T-04).
3. **Cleanup MCP subprocess при shutdown** — graceful close сессии в `main.py::run`'s `finally` (T-12).
4. **Logging MCP-вызовов** — встроенное логирование SDK достаточно? Или нужен middleware (T-11).

---

## 5. Pin'ы для requirements.txt

После research **и реальной установки** (T-03 smoke):
```
mcp[cli]>=1.20.0,<2.0      # semver! на 2026-04-25 актуальная 1.27.0 (НЕ calver как сначала думал)
chromadb>=0.5.0,<2.0
# openai уже есть (1.99.9)
```

⚠ **Гочча T-03 smoke:** при spawn'е MCP-сервера через `stdio_client` нужно явно
передать `env=dict(os.environ)` И добавить `PYTHONPATH=<repo>/mysite/` —
иначе subprocess не найдёт `mysite.settings`. В `infra/systemd/...` будем
прописывать `Environment=PYTHONPATH=/home/taximeter/mysite/formula_tela/mysite`.

---

## 6. STATUS

T-01 done. T-02 (модель `BotInquiry`) — следующая, ничего не блокирует.
