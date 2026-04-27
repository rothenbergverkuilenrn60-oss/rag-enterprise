# =============================================================================
# Dockerfile
# 企业级 RAG — 多阶段构建（builder + runtime）
# 基础镜像：python:3.11-slim（兼容 CPU / GPU 双模式）
# 构建命令：docker build -t rag-enterprise:latest .
# =============================================================================

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 1: Builder — 安装全量依赖并编译 wheel
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM python:3.11-slim AS builder

# 系统级构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        git \
        curl \
        libssl-dev \
        libffi-dev \
        libpq-dev \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 先复制依赖文件以利用 Docker layer cache
COPY requirements.txt requirements-eval.txt ./

# 升级 pip 并以 wheel 形式预编译所有依赖（加速 runtime 层安装）
RUN pip install --upgrade pip wheel \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements-eval.txt


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 2: Runtime — 最小化运行时镜像
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM python:3.11-slim AS runtime

LABEL maintainer="EnterpriseRAG Team"
LABEL version="3.0.0"
LABEL description="Enterprise RAG — FastAPI + Qdrant + BGE-M3 + RAGAS Evaluation"

# 运行时系统依赖（精简）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libpq5 \
        curl \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 创建非 root 用户（生产安全规范）
RUN groupadd -r raguser && useradd -r -g raguser -u 1001 raguser

# 工作目录与数据目录
WORKDIR /app
RUN mkdir -p \
        /app/data/raw \
        /app/data/processed \
        /app/data/index \
        /app/logs \
        /app/cache \
        /app/eval_reports \
    && chown -R raguser:raguser /app

# 安装依赖：优先用 builder 预编译的 wheels，缺失时从 PyPI 补全
COPY --from=builder /wheels /wheels
COPY requirements.txt requirements-eval.txt ./
RUN pip install --no-cache-dir --find-links=/wheels -r requirements.txt -r requirements-eval.txt \
    && rm -rf /wheels

# 复制应用代码（最后一层，保证代码变更不重建依赖层）
COPY --chown=raguser:raguser . /app/

# 环境变量默认值（生产环境通过 docker-compose / K8s Secrets 覆盖）
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    DEBUG=false \
    LOG_LEVEL=INFO \
    API_HOST=0.0.0.0 \
    API_PORT=8000

# 切换非 root 用户
USER raguser

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# 生产入口：Uvicorn 单进程（多副本通过 Compose/K8s HPA 横向扩展）
CMD ["python", "-m", "uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info", \
     "--no-access-log"]
