# VFX 4 All as a hosted server. ffmpeg comes inside the imageio-ffmpeg wheel.
#
#   docker build -t vfx4all .
#   docker run -p 8420:8420 -v vfx4all-runs:/data/runs -e COMFY_API_KEY=... -e VFX4ALL_ACCESS_CODE=... vfx4all
#
# Run it behind a reverse proxy with HTTPS, and set FORWARDED_ALLOW_IPS to the proxy's address.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VFX4ALL_MODE=hosted \
    VFX4ALL_HOST=0.0.0.0 \
    VFX4ALL_PORT=8420 \
    VFX4ALL_RUNS_DIR=/data/runs

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vfx4all/ vfx4all/
COPY presets/ presets/
COPY workflows/ workflows/
COPY web/ web/
COPY run.py LICENSE THIRD_PARTY_NOTICES.md ./

RUN useradd --create-home vfx4all && mkdir -p /data/runs && chown -R vfx4all /data
USER vfx4all
VOLUME /data/runs
EXPOSE 8420
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8420/api/health')"
CMD ["python", "run.py", "--no-browser"]
