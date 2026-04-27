# Phase 4: Image Extraction — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-24
**Phase:** 04-image-extraction
**Areas discussed:** Image filter threshold, Caption failure behavior, Base64 storage cap

---

## Image filter threshold

| Option | Description | Selected |
|--------|-------------|----------|
| 100 × 100 px | Filters decorative elements; standard document image heuristic | ✓ |
| 50 × 50 px | More permissive; risks more noise | |
| 200 × 200 px | Conservative; may miss mid-sized figures | |

**User's choice:** 100 × 100 px

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — 50 images/doc | Cap with warning log on excess | ✓ |
| No cap | Full fidelity, higher cost and latency risk | |

**User's choice:** 50 images/doc cap

---

## Caption failure behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Skip image | No chunk created; warning logged | ✓ |
| Store with fallback caption | Caption = "Image on page N of filename"; pollutes vector space | |
| Fail the document | Entire ingest fails on any caption error | |

**User's choice:** Skip image

| Option | Description | Selected |
|--------|-------------|----------|
| Partial success | success=True, skipped images in extraction_errors | ✓ |
| Full success | Caption failures invisible to caller | |

**User's choice:** Partial success — IngestionResponse.success=True, skipped images in extraction_errors

---

## Base64 storage cap

| Option | Description | Selected |
|--------|-------------|----------|
| Resize to max 1024px | Pillow thumbnail before encode; ~300KB/image bound | ✓ |
| Skip images > 2MB raw | Inconsistent — large diagrams dropped | |
| No cap | Full resolution; potential 13MB+ JSONB rows | |

**User's choice:** Resize to max 1024px using Pillow before base64 encoding

---

## Claude's Discretion

- `chunk_type` placement in Chunk vs ChunkMetadata model
- `DocType` extension approach for standalone images
- Caption prompt language (English or Chinese)

## Deferred Ideas

None.
