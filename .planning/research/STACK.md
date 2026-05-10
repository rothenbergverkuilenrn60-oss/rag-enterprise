# STACK — v1.5 Web Search + Multi-Agent Debate + Coverage Lift

*Generated 2026-05-10 inline (no subagent — `agents_installed: false`). Supersedes prior milestone research.*

## Existing capabilities (DO NOT re-research)

- Python 3.11 / FastAPI / asyncpg / Pydantic V2 (frozen models, `model_config = ConfigDict(frozen=True)`)
- LLM adapters: Anthropic (`anthropic>=0.39`), OpenAI (`openai>=1.50`), Ollama; provider-neutral `BaseLLMClient.call_agentic_turn`
- Tenacity for retry/backoff (used in v1.0+ for all external calls)
- pytest + pytest-asyncio + pytest-cov; combined coverage `--fail-under=70`; diff-cover `--fail-under=80` on touched files
- v1.4 `BaseTool` ABC + `ToolRegistry` + `AGENT_TOOL_ALLOWLIST` constant in `services/pipeline.py`
- v1.4 `Planner` / `Executor` / `Synthesizer` triad behind frozen Pydantic V2 contracts (`ToolPlan`, `ToolCall`, `ToolResult`)
- v1.3 `SwarmQueryPipeline` — coordinator decomposes → N independent sub-agents via `asyncio.gather` → synthesis LLM produces unified answer

## NEW dependencies for v1.5

### `tavily-python` (WebSearchTool real impl)

| Field | Value |
|---|---|
| **Package** | `tavily-python` (PyPI) |
| **Latest** | 0.7.24 (Apr 27, 2026) |
| **Async client** | `AsyncTavilyClient(api_key=...)` — use this; project pipeline is async-throughout |
| **Custom transport** | Accepts `httpx.AsyncClient` for proxy / gateway / auth headers |
| **Auth** | `api_key="tvly-..."` from env `TAVILY_API_KEY` |
| **Quota** | 1000 free credits/month; 1 credit per basic/fast/ultra-fast search; 2 per advanced |
| **API base** | `https://api.tavily.com/search` (REST) — SDK wraps this |

### `tavily-python` core API used in v1.5

```python
from tavily import AsyncTavilyClient

client = AsyncTavilyClient(api_key=settings.tavily_api_key)
response = await client.search(
    query="...",
    search_depth="basic",     # basic | fast | advanced | ultra-fast
    max_results=5,
    include_answer=False,     # let our synthesizer compose; don't double-summarize
    include_raw_content=False,
    include_domains=None,
    exclude_domains=None,
)
# response shape:
# {"query": str,
#  "results": [{"title", "url", "content", "score", "raw_content", "favicon"}, ...],
#  "response_time": str}
```

### Optional addition — none

No additional packages for AGENT-05 debate. The verifier role reuses existing `BaseLLMClient.call_agentic_turn` + `asyncio.gather` + `SwarmQueryPipeline` infrastructure. Coverage lift uses only existing pytest stack.

## Integration with existing config

- `.env` (gitignored): `TAVILY_API_KEY=tvly-...` (user provides; **never** committed)
- `.env.docker`: `TAVILY_API_KEY=${TAVILY_API_KEY:-}` placeholder for compose
- `utils/config.py` (Pydantic Settings): add `tavily_api_key: str = ""` + `tavily_search_depth: str = "basic"` + `tavily_max_results: int = 5`
- `requirements.txt`: append `tavily-python>=0.7.24,<0.8`
- `Dockerfile`: rebuild required (new dependency)

## What NOT to add

- Custom HTTP client for Tavily — use the SDK's `AsyncTavilyClient`; saves us auth/retry/error mapping
- Generic web-search abstraction layer (SerpAPI/Brave/Tavily switching) — premature; v1.5 ships Tavily only, abstraction emerges if a second provider is added
- Memory storage for AGENT-05 debate transcripts — debate trace flows through existing SSE; persistence is `/office-hours` v1.6 work

## References

- Tavily Python SDK: https://github.com/tavily-ai/tavily-python
- Tavily Search API: https://docs.tavily.com/documentation/api-reference/endpoint/search
- Tavily Pricing: https://docs.tavily.com/documentation/api-credits
