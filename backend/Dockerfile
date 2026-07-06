FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Install dependencies first (cached layer — only re-runs when
# requirements.txt changes, not on every code change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend code
COPY . .

# Install curl for HEALTHCHECK
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*


# Create a non-root user and give ownership of the /app directory
RUN useradd -m appuser && chown -R appuser:appuser /app

# Switch to the non-root user
USER appuser

# Fix Windows CRLF line endings and make startup script executable
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh

EXPOSE 8000

# Healthcheck to verify the server is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Ingest runs at startup (not build time) because it needs env vars
# like GROQ_API_KEY and COHERE_API_KEY which are only available at runtime
# on Render. start.sh runs ingest.py first, then starts uvicorn.
CMD ["./start.sh"]
