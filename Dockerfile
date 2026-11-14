# Build a fully self-contained container after the model has been staged in models/.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SA_HOST=0.0.0.0 SA_PORT=8765 SA_DATA_DIR=/var/lib/syllabus-auditor SA_MODEL_PATH=/opt/syllabus-auditor/models/Qwen3-1.7B-Q4_K_M.gguf
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
WORKDIR /opt/syllabus-auditor
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libgomp1 build-essential cmake && rm -rf /var/lib/apt/lists/*
COPY requirements-ai.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-ai.txt
# Preinstall a headless browser during the image build; no browser download at runtime.
RUN python -m playwright install --with-deps chromium
COPY app ./app
COPY models ./models
RUN test -s /opt/syllabus-auditor/models/Qwen3-1.7B-Q4_K_M.gguf || (echo 'Model missing. Run tools/prepare_model.py before Docker build.' && exit 1)
RUN useradd -r -u 10001 -s /usr/sbin/nologin app && mkdir -p /var/lib/syllabus-auditor && chown -R app:app /var/lib/syllabus-auditor
USER app
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=8s --start-period=30s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=5)" || exit 1
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8765","--proxy-headers","--forwarded-allow-ips","127.0.0.1"]
