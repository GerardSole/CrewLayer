# ── Stage 1: Build dashboard ──────────────────────────────────────────────────
FROM node:20-alpine AS dashboard-build
WORKDIR /dashboard
COPY dashboard/package*.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

# ── Stage 2: Python API ───────────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

COPY . .
RUN pip install --no-cache-dir -e .

# Copy built dashboard into the location main.py expects
COPY --from=dashboard-build /dashboard/dist ./dashboard/dist

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
