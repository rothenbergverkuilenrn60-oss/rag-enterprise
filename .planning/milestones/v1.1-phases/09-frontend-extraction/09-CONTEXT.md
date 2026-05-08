# Phase 9: Frontend Extraction - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning

<domain>
## Phase Boundary

将 `main.py:385` 的 inline `_UI_HTML` triple-quoted 字符串及 `@app.get("/ui")` 路由（line 446-448）替换为：
- `static/ui.html` 单文件（含原 inline `<style>` 和 `<script>`，**保持 inline 不拆分**）
- `app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")`
- Docker 镜像通过 `COPY static/` 包含静态资源

**本质：纯 refactor，no behavioural change vs v1.0**。Acceptance #2 "renders identically" 是行为锚点。

**In scope:**
- 抽 `_UI_HTML` 字符串到 `static/ui.html`
- 替换 `/ui` 路由为 StaticFiles mount
- Dockerfile 加 `COPY static/`
- 验证 `http://localhost:8000/ui/` 行为与 v1.0 一致

**Out of scope:**
- JS 拆 `static/ui.js`（D-01 决定保留 inline，v1.2 候选）
- CSS 拆 `static/ui.css`（D-02 决定保留 inline，v1.2 候选）
- 变量重命名 / HTML 重缩进 / 语义重构（D-04 决定纯搬，v1.2 候选）
- 显式 `/ui`（不带斜杠）路由（D-03 决定接受 307 默认重定向）
- 任何 build step / bundler / 新 npm 依赖（v1.1 milestone OOS 明示）

</domain>

<decisions>
## Implementation Decisions

### JS 抽出策略
- **D-01:** Inline `<script>` 保留在 `ui.html` 单文件内，**不抽** `static/ui.js`。
  - **Why:** Acceptance #1 明示 "Inline JS may stay"；现 28 行 JS 极小；保留 inline = 单资源加载、零 FOUC、严守 acceptance "renders identically" 的最低验证表面；v1.2 真要做 UI 升级时再独立抽，作为 v1.2 Phase 候选。

### CSS 抽出策略
- **D-02:** Inline `<style>` 保留在 `ui.html` 单文件内，**不抽** `static/ui.css`。
  - **Why:** 与 D-01 对称——避免 JS 保留 / CSS 抽出的中间态降低代码可读性。13 行 CSS 极小，单资源 first paint 更快。v1.2 design tokens 工作再独立抽。

### Trailing-slash 行为
- **D-03:** 接受 FastAPI StaticFiles `html=True` 的默认行为：`/ui` 返回 307 重定向到 `/ui/`，`/ui/` 直接返 `ui.html`。**不**加显式 `/ui` 路由防御。
  - **Why:** 零额外代码；FastAPI 默认；老书签 `/ui` 仍最终可达；nginx 等反代默认透传 307；acceptance #2 仅要求 `/ui/` work。如未来部署在严格反代下出现问题，再以 v1.2 small bug-fix 加显式路由。

### 顺手清理范围
- **D-04:** **零清理**——`_UI_HTML` 字符串内容**一字不改**搬到 `static/ui.html`。变量名 `j h m btn out`、`out.innerHTML` 字符串拼接、HTML 缩进**全部保留原样**。
  - **Why:** 严守 acceptance #2 "renders identically"；纯搬是隐性 bug 风险 = 0 的唯一路径；任何 cosmetic 重构（变量重命名 / DOM API 替换 innerHTML / esc 函数审计）→ v1.2 独立 Phase。

### Claude's Discretion
（planner / executor 决定 HOW）
- `static/` 目录在项目根创建（acceptance #2 写死 `directory="static"`，相对 `main.py` 工作目录 = 项目根）
- Dockerfile 修改位置：现有 `COPY` 指令是否覆盖 `static/`，要看 Dockerfile 原文（planner 读后决定加单独 line 还是包在现有 COPY 里）
- 测试策略：integration test（httpx + StaticFiles 端到端）vs unit test（route mount 注册）vs 两者都做——planner 视情况选
- 静态资源 ETag / cache-control 头：StaticFiles 默认行为可接受，无需配置
- 删除 `from fastapi.responses import HTMLResponse`（如 `/ui` 是唯一 HTMLResponse 使用方）

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 9 spec
- `.planning/REQUIREMENTS.md` §"REQ B-1 (UI-01): Extract inline HTML to a single static asset; serve via FastAPI StaticFiles" — 5 acceptance criteria，本 phase 全部 success criteria 来源
- `.planning/ROADMAP.md` §"Phase 9: Frontend Extraction" — Goal + Success Criteria 4 项

### 现有代码（要改的）
- `main.py:385-444` — `_UI_HTML` triple-quoted 字符串（含 inline `<style>` line 6-19 + inline `<script>` line 29-57，相对 `_UI_HTML` 字符串内行号）
- `main.py:446-448` — `@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)` 路由 + handler

### Docker 上下文（要改）
- `Dockerfile`（项目根）— 加 `COPY static/` 或确保现有 `COPY .` 覆盖
- `docker-compose.yml` — 不应需要 bind-mount，container 内 `static/` 由 image 自带

### v1.1 milestone 上下文
- `.planning/PROJECT.md` §"Current Milestone: v1.1 Retrieval Depth & Frontend" — 三 track 上下文（Track B = 本 phase 唯一 phase）
- `.planning/STATE.md` — Phase 7+8 已 shipped (PR #1)，Phase 9 状态（in_progress 后由 state.record-session 填）

### 不直接相关（但 phase 8 context 已 frozen，避免任何冲突）
- `.planning/phases/08-multimodal-metadata-query-filter/08-CONTEXT.md` — Phase 8 决定，不与 Phase 9 交叉

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `main.py` 已 import `from fastapi.staticfiles import StaticFiles`（如已存在）—— planner 验证
- `Dockerfile` 现有 `COPY` 指令模式 —— planner 读后决定是否需新增

### Established Patterns
- 项目三层架构 `utils/ → services/ → controllers/`：`static/` 作为顶层 asset 目录，**不属任一层**——这是合理 frontend boundary（routing 位于 `main.py`/controllers，asset 与 logic 分离）
- 现 inline UI 模式在 `main.py` 而非 `controllers/`——本 phase 不动这点（acceptance 仅说"`main.py` 移除 `_UI_HTML`"）

### Out-of-the-way patterns to NOT propagate
- `_UI_HTML` 三引号字符串内的 JS 风格（变量短名 / `innerHTML` 拼接）是 v1.0 历史包袱，**不复制到将来代码**——v1.2 真做 UI 升级时清理

</code_context>

## Deferred Ideas

捕获于 D-01/02/04 决定中，归入 v1.2 候选：
1. **抽 JS 到 `static/ui.js`** —— v1.2 UI feature 添加时启动
2. **抽 CSS 到 `static/ui.css` + design tokens** —— v1.2 视觉优化
3. **重构 inline JS（DOM API / template literal / 变量重命名 / esc 审计）** —— v1.2 frontend 现代化
4. **显式 `/ui` 无斜杠路由** —— 仅当部署在严格反代下出问题再加
5. **Multi-channel SSE 输出 frontend 展示**（来自 office-hours design doc）—— Phase 11 swarm 升级时复用 `static/ui.html` 加 SSE 客户端代码
