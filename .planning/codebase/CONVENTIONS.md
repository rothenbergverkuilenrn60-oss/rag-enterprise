# Coding Conventions

## Summary

This codebase is an enterprise RAG system written in Python 3.11 with async-first design. All service modules follow a consistent pipeline-stage structure with Pydantic V2 models as inter-stage contracts. Code style is enforced by ruff (lint) and mypy (type checking) via CI, with loguru used throughout for structured logging.

## Naming Patterns

**Files:**
- `snake_case` for all `.py` files: `chunker.py`, `retriever.py`, `feedback_service.py`
- Service files named by role: `{noun}_service.py` or `{noun}.py`
- Test files: `test_{module}.py` mirroring the module they test

**Classes:**
- `PascalCase`: `RecursiveTextSplitter`, `DocProcessorService`, `GeneratorService`
- Pydantic models: `PascalCase` nouns matching their stage: `RawDocument`, `ExtractedContent`, `DocumentChunk`, `RetrievedChunk`
- Enums: `PascalCase` class, `UPPER_SNAKE_CASE` members: `DocType.PDF`, `ChunkStrategy.RECURSIVE`

**Functions and methods:**
- `snake_case`: `rrf_fusion`, `adaptive_rrf_fusion`, `count_tokens`, `detect_language`
- Private helpers prefixed with `_`: `_split_recursive`, `_make_chunk_id`, `_process_tables`
- Factory functions: `get_{noun}()` pattern: `get_preprocessor()`, `get_embedder()`, `get_vector_store()`
- Decorator helpers: `log_latency` (no prefix, decorates both sync and async)

**Variables:**
- `snake_case` throughout
- Type-annotated locals where useful: `scores: defaultdict[str, float]`, `chunks: list[str]`
- Booleans: `is_duplicate`, `use_contextual`, `supports_tools`, `supports_thinking`

**Constants:**
- Module-level private constants: `_SEPARATORS_ZH`, `_MAX_FULL_TEXT_CHARS`
- Settings accessed via `settings.*` singleton (never hardcoded inline)

## Code Style

**Formatting:**
- No black/isort configured locally; ruff handles linting
- CI runs: `ruff check . --select E,F,W,I --ignore E501` (line length not enforced)
- `from __future__ import annotations` used in all service and model files

**Linting:**
- Tool: `ruff==0.8.6` (selects E, F, W, I — errors, pyflakes, warnings, isort)
- E501 (line length) is explicitly ignored — long lines are acceptable
- `bandit==1.8.0` for security scanning (B101/B601 skipped; `continue-on-error: true` in CI)

**Type hints:**
- Present on all public function signatures
- Return types always annotated: `-> list[str]`, `-> None`, `-> int`
- Modern union syntax used: `str | None`, `list[float] | None`
- Pydantic V2 `BaseModel` used for all inter-stage data structures
- mypy configured with `--ignore-missing-imports --no-strict-optional`; failures are non-blocking in CI (`continue-on-error: true`)

## Import Organization

**Order (enforced by ruff/isort):**
1. `from __future__ import annotations`
2. Standard library (`asyncio`, `hashlib`, `re`, `time`, `uuid`)
3. Third-party (`loguru`, `pydantic`, `tenacity`)
4. Local (`config.settings`, `utils.models`, `utils.logger`, `services.*`)

**Pattern:**
- No barrel `__init__.py` re-exports for business logic (each file imported directly)
- `__init__.py` files are present but empty in service subdirectories

## File Structure Pattern

Each source file opens with a section header block:
```python
# =============================================================================
# services/module/file.py
# STAGE N — Brief description
# =============================================================================
```

Logical sections within files are delimited by:
```python
# ══════════════════════════════════════════════════════════════════════════════
# Section Name
# ══════════════════════════════════════════════════════════════════════════════
```

## Error Handling

**Pattern — graceful degradation with logging:**
All service methods catch exceptions explicitly and fall back to a safe default rather than propagating. The `raise` is used only inside `log_latency` wrapper after logging.

```python
try:
    result = await llm.chat(...)
    return result
except Exception as exc:
    logger.warning(f"[component] operation failed: {exc}, falling back to default")
    return fallback_value
```

**Tenacity retry:** `@retry(stop=stop_after_attempt(N), wait=wait_random_exponential(...))` used on external I/O (vector store, embedder calls) in `services/retriever/retriever.py`.

**Fallback chains:**
- LLM unavailable → keyword overlap / static header / original text
- tiktoken missing → character-estimate fallback in `count_tokens()`
- Proposition split LLM failure → return `[original_chunk_text]`

**Never silent swallows:** Every except block logs at `logger.warning` or `logger.error` before returning the fallback.

## Logging

**Framework:** `loguru` (not stdlib `logging`)

**Setup:** `utils/logger.py` — `setup_logger()` called once at app startup in `main.py` lifespan.

**Outputs:**
- Console: colorized human-readable format
- File: JSON structured, daily rotation, 30-day retention, gzip compression, async enqueue

**Usage pattern:**
```python
from loguru import logger
logger.debug(...)
logger.info(...)
logger.warning(...)
logger.error(...)
```

**Latency decorator:** `@log_latency` from `utils/logger.py` wraps both sync and async functions. Logs `DEBUG` on success, `ERROR` on exception (then re-raises).

## Docstring Style

Short one-line Chinese-language docstrings are used for classes and key methods:
```python
class DocType(str, Enum):
    """文档类型枚举，继承 str 使其可直接用作字符串比较。"""
```

Multi-line docstrings use Chinese narrative with Chinese section labels:
```python
def adaptive_rrf_fusion(...):
    """
    自适应 RRF：根据各路结果的质量动态调整权重。

    权重计算策略：
      - ...
    """
```

Inline comments are used liberally in Chinese explaining the *why*, not the *what*.

## Pydantic Model Conventions

- All inter-stage data: `BaseModel` subclass, never plain dicts
- Fields: `Field(default_factory=...)`, `Field(..., description="...")` for required fields
- `field_validator` used for validation logic inside models
- `model_post_init` used for derived field computation (e.g., auto-computing `char_count`)
- `str | None` with `None` default for optional string fields

## Async Conventions

- `asyncio_mode = auto` in pytest.ini (no need for `@pytest.mark.asyncio` in newer tests, though it appears on older ones)
- All pipeline stage methods are `async def`
- `asyncio.gather()` used for parallel execution within stages
- `AsyncMock` / `MagicMock` pattern for LLM client mocking in tests

## Sources

- `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/services/doc_processor/chunker.py`
- `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/services/retriever/retriever.py`
- `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/utils/models.py`
- `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/utils/logger.py`
- `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/requirements-dev.txt`
- `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/.github/workflows/ci.yml`
- All files under `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/tests/`
