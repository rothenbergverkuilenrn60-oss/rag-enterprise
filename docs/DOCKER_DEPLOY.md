# Docker 部署 & RAGAS 评测指南

## 一、目录结构（新增文件）

```
rag_enterprise/
├── Dockerfile                    # 多阶段生产镜像
├── docker-compose.yml            # 完整服务编排
├── .dockerignore                 # 构建上下文过滤
├── .env.docker                   # Docker 环境变量模板
├── Makefile                      # 常用操作快捷命令
├── requirements-eval.txt         # RAGAS 评测专用依赖
│
├── docker/
│   ├── eval/
│   │   └── Dockerfile.eval       # RAGAS 评测专用镜像
│   ├── qdrant/
│   │   └── config.yaml           # Qdrant 生产配置
│   ├── redis/
│   │   └── redis.conf            # Redis 生产配置
│   ├── nginx/
│   │   ├── nginx.conf            # Nginx 主配置
│   │   └── conf.d/rag.conf       # RAG API 虚拟主机
│   └── ollama/
│       └── pull_models.sh        # 模型预加载脚本
│
├── eval/
│   ├── __init__.py
│   ├── models.py                 # Pydantic 评测数据模型
│   ├── ragas_runner.py           # RAGAS 评测引擎（主逻辑）
│   ├── report_renderer.py        # HTML 报告渲染器
│   └── datasets/
│       └── qa_pairs.json         # 示例评测数据集（10条）
│
└── tests/
    └── integration/
        └── test_ragas_eval.py    # RAGAS 评测集成测试
```

---

## 二、快速启动

### 1. 准备环境变量

```bash
cp .env.docker .env.docker.local
# 编辑 .env.docker.local，填写以下必填项：
#   SECRET_KEY      — 生产必须替换为随机256位密钥
#   OPENAI_API_KEY  — RAGAS judge model 使用（可选，评测时需要）
```

### 2. 构建镜像

```bash
# 方法一：Makefile（推荐）
make build

# 方法二：直接 docker compose
docker compose build --no-cache
```

### 3. 启动完整服务栈

```bash
# 启动全部服务（Qdrant + Redis + Ollama + RAG API + Nginx）
make up
# 等价于：
docker compose --env-file .env.docker up -d

# 分步启动（推荐首次部署）
make up-infra   # 先启动基础设施
# 等待 Ollama 拉取模型（约 5-10 分钟，取决于网速）
make up-api     # 再启动 API 服务
```

### 4. 验证服务就绪

```bash
make health
# 输出示例：
# {
#   "status": "ok",
#   "app": "EnterpriseRAG",
#   "version": "3.0.0",
#   ...
# }

make readiness
# 检查 Redis 和 Qdrant 连通性
```

### 5. 查看日志

```bash
make logs        # rag-api 实时日志
make logs-all    # 所有服务日志
```

---

## 三、服务说明

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| rag-api | rag-enterprise:latest | 8000 | FastAPI 主应用 |
| qdrant | qdrant/qdrant:v1.11.5 | 6333/6334 | 向量数据库 |
| redis | redis:7.4-alpine | 6379 | 缓存 |
| ollama | ollama/ollama:0.5.4 | 11434 | 本地 LLM 推理 |
| nginx | nginx:1.27-alpine | 80/443 | 反向代理 |
| ragas-eval | rag-enterprise-eval:latest | — | 评测（一次性） |

---

## 四、RAGAS 评测

### 4.1 评测数据集格式

编辑 `eval/datasets/qa_pairs.json`：

```json
{
  "name": "我的评测数据集",
  "version": "1.0.0",
  "created_at": "2025-01-01T00:00:00",
  "pairs": [
    {
      "question": "什么是RAG技术？",
      "ground_truth": "RAG是检索增强生成技术...",  // 可选，用于 answer_correctness
      "metadata": {"category": "概念"}
    }
  ]
}
```

### 4.2 运行评测

```bash
# Docker 方式（推荐生产环境）
make eval
# 等价于：
docker compose --env-file .env.docker run --rm ragas-eval

# 本地方式（开发调试）
make eval-local
# 等价于：
conda run -n torch_env python -m eval.ragas_runner
```

### 4.3 评测指标说明

| 指标 | 说明 | 范围 |
|------|------|------|
| **Faithfulness** | 答案是否忠实于检索上下文（不幻觉） | 0~1 |
| **Answer Relevancy** | 答案与问题的相关程度 | 0~1 |
| **Context Precision** | 检索到的上下文有多少是相关的 | 0~1 |
| **Context Recall** | 答案所需信息是否被检索到 | 0~1 |
| **Answer Correctness** | 答案与参考答案的一致性（需 ground_truth）| 0~1 |

**生产达标线：Overall Score ≥ 0.6（评测脚本退出码 0 = 通过）**

### 4.4 评测报告

报告自动写入 `eval_reports/` 目录（Docker 卷挂载）：

- `eval_{run_id}_{timestamp}.json` — 结构化 JSON（可对接 CI/CD）
- `eval_{run_id}_{timestamp}.html` — 可视化 HTML 报告

### 4.5 Judge Model 选择

在 `.env.docker` 中配置：

```bash
# 方案一：OpenAI GPT-4o（评测质量最高，推荐）
RAGAS_JUDGE_PROVIDER=openai
RAGAS_JUDGE_MODEL=gpt-4o
OPENAI_API_KEY=sk-...

# 方案二：Anthropic Claude（备选）
RAGAS_JUDGE_PROVIDER=anthropic
RAGAS_JUDGE_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...

# 方案三：本地 Ollama（无需 API Key，质量较低）
RAGAS_JUDGE_PROVIDER=ollama
RAGAS_JUDGE_MODEL=qwen2.5:14b
```

---

## 五、运行测试

```bash
# 全部测试
make test

# 仅评测集成测试（含 Mock，无需真实 API）
make test-eval

# 仅单元测试
make test-unit
```

---

## 六、GPU 支持（可选）

在 `docker-compose.yml` 中取消注释 Ollama 的 `deploy` 配置：

```yaml
ollama:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: all
            capabilities: [gpu]
```

前置条件：
```bash
# 安装 NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/libnvidia-container/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

---

## 七、生产清单

- [ ] `SECRET_KEY` 替换为 256 位随机密钥（`openssl rand -hex 32`）
- [ ] `QDRANT_API_KEY` 设置 Qdrant 认证密钥
- [ ] Redis 密码配置（`redis.conf` → `requirepass`）
- [ ] Nginx TLS 证书挂载（Let's Encrypt 或企业证书）
- [ ] 数据卷备份策略（`qdrant-storage`、`redis-data`）
- [ ] 评测 CI/CD 集成（PR 门禁：Overall Score ≥ 0.6）
- [ ] `LANGFUSE_ENABLED=true` 开启 LLM 可观测性
