FROM python:3.15-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Install dependencies first (cached layer — only re-runs when
# requirements.txt changes, not on every code change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend code
COPY . .

# NOTE: If Render's build context is set to the root directory, 
# this will copy the whole repo. If it's set to 'backend', we can't access 'frontend'.

# Install curl for HEALTHCHECK
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*


# Create a non-root user and give ownership of the /app directory
RUN useradd -m appuser && chown -R appuser:appuser /app

# Switch to the non-root user
USER appuser

# Fix Windows CRLF line endings and make startup scripts executable
RUN sed -i 's/\r$//' start.sh pre_deploy.sh && chmod +x start.sh pre_deploy.sh

EXPOSE 8000

# Healthcheck to verify the server is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# start.sh runs `alembic upgrade head` and then starts uvicorn. Policy-doc ingestion
# (needs GROQ/COHERE/PINECONE env vars, so it can't run at build time) lives in
# pre_deploy.sh, which Render runs as its preDeployCommand.
CMD ["./start.sh"]
