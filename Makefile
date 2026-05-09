# =============================================================================
# Makefile
# 企业级 RAG — 常用操作命令
# 使用：make <target>
# =============================================================================

.PHONY: help build up down logs shell ingest eval clean coverage-diff coverage-combined demo-agent demo-agent-record

COMPOSE = docker compose
SERVICE = rag-api
EVAL_SERVICE = ragas-eval

help:  ## 显示帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-20s\033[0m %s\n",$$1,$$2}'

# ── 镜像构建 ──────────────────────────────────────────────────────────────────
build:  ## 构建所有镜像
	$(COMPOSE) build --no-cache

build-api:  ## 仅构建 rag-api 镜像
	$(COMPOSE) build --no-cache $(SERVICE)

build-eval:  ## 仅构建 ragas-eval 镜像
	$(COMPOSE) build --no-cache $(EVAL_SERVICE)

# ── 服务启停 ──────────────────────────────────────────────────────────────────
up:  ## 启动全栈（后台）
	$(COMPOSE) --env-file .env.docker up -d

up-infra:  ## 仅启动基础设施（Qdrant + Redis + Ollama）
	$(COMPOSE) --env-file .env.docker up -d qdrant redis ollama

up-api:  ## 启动基础设施 + RAG API
	$(COMPOSE) --env-file .env.docker up -d qdrant redis ollama rag-api

down:  ## 停止并移除容器（保留数据卷）
	$(COMPOSE) down

down-v:  ## 停止并移除容器 + 数据卷（⚠️ 数据清空）
	$(COMPOSE) down -v

restart:  ## 重启 rag-api
	$(COMPOSE) restart $(SERVICE)

# ── 日志 ──────────────────────────────────────────────────────────────────────
logs:  ## 查看 rag-api 实时日志
	$(COMPOSE) logs -f $(SERVICE)

logs-all:  ## 查看所有服务日志
	$(COMPOSE) logs -f

# ── 开发调试 ──────────────────────────────────────────────────────────────────
shell:  ## 进入 rag-api 容器 shell
	$(COMPOSE) exec $(SERVICE) /bin/bash

shell-eval:  ## 进入 ragas-eval 容器 shell
	$(COMPOSE) run --rm --entrypoint /bin/bash $(EVAL_SERVICE)

# ── 数据摄取 ──────────────────────────────────────────────────────────────────
ingest:  ## 批量摄取 /app/data/raw 目录下的文档
	$(COMPOSE) exec $(SERVICE) python scripts/ingest_batch.py

# ── RAGAS 评测 ────────────────────────────────────────────────────────────────
eval:  ## 运行 RAGAS 评测（一次性任务）
	$(COMPOSE) --env-file .env.docker run --rm $(EVAL_SERVICE)

eval-local:  ## 本地（非Docker）运行评测
	conda run -n torch_env python -m eval.ragas_runner

# ── Agent 演示 (Phase 19) ──────────────────────────────────────────────────────
demo-agent:  ## 演示 Planner→Executor→Synthesizer 4 路并行 (Phase 19, AGENT-08)
	APP_MODEL_DIR=$${APP_MODEL_DIR:-/tmp} .venv/bin/python -m services.agent._demo_runner

demo-agent-record:  ## 录制 docs/demo.cast (维护任务，需要 asciinema)
	@command -v asciinema >/dev/null 2>&1 || { echo "asciinema not installed; install via: pipx install asciinema"; exit 1; }
	asciinema rec docs/demo.cast --overwrite \
		--command "APP_MODEL_DIR=$${APP_MODEL_DIR:-/tmp} .venv/bin/python -m services.agent._demo_runner"

# ── 健康检查 ──────────────────────────────────────────────────────────────────
health:  ## 检查 rag-api 健康状态
	curl -s http://localhost:8000/api/v1/health | python3 -m json.tool

readiness:  ## 检查服务就绪状态
	curl -s http://localhost:8000/api/v1/readiness | python3 -m json.tool

# ── 测试 ──────────────────────────────────────────────────────────────────────
test:  ## 运行全部单元测试（本地）
	conda run -n torch_env pytest tests/ -v --timeout=30

test-eval:  ## 仅运行评测集成测试
	conda run -n torch_env pytest tests/integration/test_ragas_eval.py -v

test-unit:  ## 仅运行单元测试
	conda run -n torch_env pytest tests/unit/ -v

coverage-diff:  ## Run diff-cover locally against origin/master...HEAD (TEST-03)
	@echo ">> Fetching origin/master to ensure baseline is current..."
	git fetch origin master
	@echo ">> Running unit tests with coverage XML output..."
	conda run -n torch_env pytest tests/unit/ \
		--asyncio-mode=auto \
		--timeout=30 \
		--cov=services \
		--cov=utils \
		--cov-report=xml:coverage.xml \
		-q
	@echo ">> Running diff-cover against origin/master..."
	conda run -n torch_env diff-cover coverage.xml \
		--compare-branch=origin/master \
		--fail-under=80 \
		--html-report diff-cover.html
	@echo ">> diff-cover.html written. Open in browser to inspect uncovered lines."

# ── 清理 ──────────────────────────────────────────────────────────────────────
clean:  ## 清理构建缓存和悬空镜像
	docker system prune -f
	docker image prune -f

clean-reports:  ## 清理评测报告
	rm -f eval_reports/eval_*.json eval_reports/eval_*.html

coverage-combined:  ## Mirror CI: combined unit+integration coverage report (TEST-04 + TEST-06)
	@echo ">> Erasing prior coverage data..."
	conda run -n torch_env coverage erase
	@echo ">> Running unit tests with coverage (separate data file)..."
	COVERAGE_FILE=.coverage.unit conda run -n torch_env pytest tests/unit/ \
		--asyncio-mode=auto --timeout=30 \
		--cov=services --cov=utils --cov-report= -q
	@echo ">> Running integration tests with --cov-append..."
	COVERAGE_FILE=.coverage.integration conda run -n torch_env pytest tests/integration/ \
		--asyncio-mode=auto --timeout=60 \
		--cov=services --cov=utils --cov-append --cov-report= -q || true
	@echo ">> Combining and reporting..."
	conda run -n torch_env coverage combine --keep .coverage.unit .coverage.integration
	conda run -n torch_env coverage report
	conda run -n torch_env coverage report --fail-under=70
