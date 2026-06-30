FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached layer — only re-runs when
# requirements.txt changes, not on every code change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend code
COPY . .

# Fix Windows CRLF line endings and make startup script executable
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh

EXPOSE 8000

# Ingest runs at startup (not build time) because it needs env vars
# like GROQ_API_KEY and COHERE_API_KEY which are only available at runtime
# on Render. start.sh runs ingest.py first, then starts uvicorn.
CMD ["./start.sh"]
