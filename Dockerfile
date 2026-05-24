FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/french-csgo/usb-cloner"
LABEL org.opencontainers.image.description="USB Key Manager — CS2 Tournament"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      util-linux \
      coreutils \
      mount \
      udev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

RUN mkdir -p /data /mnt/sshd

EXPOSE 5000

CMD ["python", "backend/app.py"]
