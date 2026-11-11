# ping_me - container image
FROM python:3.13-slim

WORKDIR /app

# Install dependencies first for better build-layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY main.py .

# Hosts like Render / Railway / Fly inject PORT; default to 8000 for local runs.
ENV PORT=8000
EXPOSE 8000

# JSON/exec form keeps clean OS-signal handling; sh -c still expands ${PORT}.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
