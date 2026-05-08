# Phase 9: Frontend Extraction - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-08
**Phase:** 9-frontend-extraction
**Areas discussed:** JS strategy, CSS strategy, Trailing slash, Cleanup

---

## Area A — JS 抽出策略

| Option | Description | Selected |
|--------|-------------|----------|
| A1) 保留 inline，一个 ui.html 打包 | 严守 acceptance "no behavioural change"，单资源加载零 FOUC，28 行 JS 极小 | ✓ |
| A2) 抽为 static/ui.js | 后续 v1.2 可独立 lint / dev tool source map；ui.html 仅语义 markup | |
| A3) 抽出但同文件（仅调整、提 esc 至顶部加注释） | 轻量重构不拆文件 | |

**User's choice:** A1
**Notes:** 与 v1.1 milestone "no build step / no new dependencies" 约束契合；v1.2 候选

---

## Area B — CSS 抽出策略

| Option | Description | Selected |
|--------|-------------|----------|
| B1) 保留 inline（与 A 一致） | 单资源 page、零 FOUC，13 行 CSS 极小 | ✓ |
| B2) 抽为 static/ui.css | 后续独立调 design tokens；与 A1 不一致引入中间态 | |

**User's choice:** B1
**Notes:** 与 A1 对称避免一致性破坏

---

## Area C — `/ui` vs `/ui/` trailing-slash

| Option | Description | Selected |
|--------|-------------|----------|
| C1) 接受 307 重定向（默认） | 零额外代码；FastAPI 默认；老书签仍可达 | ✓ |
| C2) 加明示 /ui RedirectResponse 301 | 显式控制 redirect 状态码 | |
| C3) 加明示 /ui 直接返 ui.html | 零 redirect、零额外跳；代码重复渲染逻辑 | |

**User's choice:** C1
**Notes:** acceptance #2 仅要求 `/ui/` work，未规定 `/ui` 行为；如反代严格再补

---

## Area D — Inline UI 是否顺手清理

| Option | Description | Selected |
|--------|-------------|----------|
| D1) 纯搬，一字不改 | 严守 acceptance "renders identically"，bug 风险 0 | ✓ |
| D2) 轻量整理（变量重命名 + HTML 缩进 + 加注释） | 可读性提升不改逻辑；纯人工 review 验证 "identical" 不现实 | |
| D3) 重构（innerHTML → DOM API / template literal） | 升 XSS 防护 + 可读；明显超 acceptance | |

**User's choice:** D1
**Notes:** v1.2 真做 UI 升级时清理，作为独立 phase 而非顺手

---

## Claude's Discretion

- `static/` 目录在项目根创建（acceptance #2 写死 `directory="static"` 相对路径）
- Dockerfile `COPY static/` 加在哪行（planner 读 Dockerfile 后决定）
- 测试策略选择（integration vs unit vs 两者）
- 是否删 `from fastapi.responses import HTMLResponse` import（视该 import 是否仅 `/ui` 路由使用）

## Deferred Ideas

1. JS 抽 `static/ui.js`（v1.2 UI feature 候选）
2. CSS 抽 `static/ui.css` + design tokens（v1.2 视觉优化）
3. Inline JS 重构（DOM API / 变量重命名 / esc 审计）
4. 显式 `/ui` 无斜杠路由（仅严格反代部署出问题再加）
5. Multi-channel SSE 输出 frontend 展示（Phase 11 swarm 升级复用 `static/ui.html` 加 SSE 客户端代码）
