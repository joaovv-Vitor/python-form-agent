FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    HF_HUB_CACHE=/var/cache/models \
    WEB_DATA_DIR=/var/lib/form-agent \
    WEB_HOST=0.0.0.0 \
    WEB_FRONTEND_DIR=/app/frontend/dist
WORKDIR /app
COPY pyproject.toml README.md LICENSE model-profiles.json ./
COPY src/ ./src/
RUN python -m pip install '.[audio,web]' \
    && python -m playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /var/lib/form-agent /var/cache/models \
    && chown -R app:app /var/lib/form-agent /var/cache/models
COPY --from=frontend /build/dist/ ./frontend/dist/
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["form-web-py"]
