FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.11-slim
LABEL agent.schema="0004" agent.safety-contract="2026-10-10"
WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/app/model-cache
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-ci.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
COPY migrations migrations
COPY alembic.ini .
COPY frontend frontend
COPY --from=frontend-build /frontend/dist frontend/dist
COPY scripts scripts
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
