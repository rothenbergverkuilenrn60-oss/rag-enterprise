FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    uvloop==0.21.0 \
    sentence-transformers==3.3.1 \
    torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu \
    prometheus-client==0.21.0 \
    loguru==0.7.2 \
    pydantic==2.9.2

COPY services/reranker_service/app.py /app/app.py

ENV RERANKER_MODEL_PATH=cross-encoder/ms-marco-MiniLM-L-6-v2
ENV PYTHONUNBUFFERED=1

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001", \
     "--workers", "2", "--loop", "uvloop"]
