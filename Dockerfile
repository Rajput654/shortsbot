# Dockerfile — for Render.com deployment
# Uses Python + FFmpeg base image

FROM python:3.11-slim

# Install FFmpeg and system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create output directories
RUN mkdir -p output assets/music assets/font

# Download a free font for captions
RUN python -c "\
import urllib.request; \
urllib.request.urlretrieve( \
  'https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf', \
  'assets/font.ttf' \
)" || echo "Font download skipped - will use system font"

CMD ["python", "main.py"]
