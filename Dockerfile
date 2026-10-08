# --- frontend (Vue 3 + Vite) -> static files
FROM node:22-alpine AS front
WORKDIR /front
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npx vite build --outDir /static

# --- backend (FastAPI)
FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/wolfy ./wolfy
COPY --from=front /static ./static
COPY espbar/firmware.bin espbar/firmware-dual.bin espbar/firmware-bt.bin ./espbar/
ENV WOLFY_STATIC=/app/static WOLFY_DATA=/data WOLFY_ESPBAR_FIRMWARE=/app/espbar/firmware.bin PYTHONUNBUFFERED=1
EXPOSE 8420
CMD ["uvicorn", "wolfy.main:app", "--host", "0.0.0.0", "--port", "8420", "--proxy-headers"]
