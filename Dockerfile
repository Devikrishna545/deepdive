# DeepDive container: Hugging Face Spaces (Docker SDK) or any container host.
# Secrets (MESH_API_KEY, TAVILY_API_KEY, RUN_ACCESS_CODE) come from the host's settings, never the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=7860 DEV_MODE=false

# Hugging Face Spaces runs containers as user 1000; the app writes its SQLite DB and uploads to /app/data.
RUN useradd --create-home --uid 1000 user
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=user:user . .
RUN mkdir -p data/uploads && chown -R user:user /app/data
USER user

EXPOSE 7860
# --proxy-headers: the host terminates HTTPS; the app then sees https and sends HSTS.
CMD ["sh", "-c", "uvicorn app:create_app --factory --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
