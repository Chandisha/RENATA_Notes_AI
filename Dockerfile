# RENATA - Meeting Intelligence System Dockerfile
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    pulseaudio \
    xvfb \
    wget \
    gnupg \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Set up environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV MODELS_DIR=/var/lib/renata/models
ENV OUTPUT_DIR=/var/lib/renata/meeting_outputs

# Create directories and set permissions
RUN mkdir -p /app /var/lib/renata/models /var/lib/renata/meeting_outputs
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium
RUN playwright install-deps

# Copy the rest of the application
COPY . .

# Create a startup script to handle PulseAudio and Xvfb
RUN echo '#!/bin/bash\n\
# Start PulseAudio\n\
pulseaudio -D --exit-idle-time=-1\n\
# Load the null-sink module\n\
pactl load-module module-null-sink sink_name=renata_sink sink_properties=device.description=Renata_Virtual_Audio\n\
# Set it as default\n\
pactl set-default-sink renata_sink\n\
\n\
# Start the application\n\
exec uvicorn main:app --host 0.0.0.0 --port $PORT\n\
' > /app/start.sh && chmod +x /app/start.sh

EXPOSE $PORT

CMD ["/app/start.sh"]
