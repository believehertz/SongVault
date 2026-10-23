FROM python:3.11-slim

# Install system dependencies (FFmpeg for audio extraction)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements from root and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all backend code from the songvault-backend subfolder into /app
COPY songvault-backend/ .

# Expose FastAPI port
EXPOSE 8000

# Start Uvicorn pointing directly to main:app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]