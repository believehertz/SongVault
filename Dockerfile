FROM python:3.10-slim

# Install system dependencies including ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements from root and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend files from songvault-backend into /app
COPY songvault-backend/ .

# Expose port and run FastAPI via uvicorn
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]