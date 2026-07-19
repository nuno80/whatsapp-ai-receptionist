FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (for caddy, etc if needed)
# Not strictly required for the python app if Caddy is a separate service,
# but we need ffmpeg for whisper audio processing
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Command to run the application
CMD ["uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8000"]
