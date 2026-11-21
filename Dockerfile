# syntax=docker/dockerfile:1.7
# FakeCollector / Follow the Fake - one image for the UI and the batch pipeline (owner W4).
#   docker compose build
#   docker compose up app                     # UI on http://localhost:8501
#   docker compose --profile pipeline run --rm pipeline
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System packages:
#   tesseract-ocr + pol traineddata -> OCR in the visual module
#   libgl1, libglib2.0-0           -> runtime libraries OpenCV needs on slim images
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-pol libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first (cached layer while only code changes).
COPY requirements.txt ./
COPY requirements/ ./requirements/
# CPU-only torch: the versions are read from requirements/visual.txt so the pin lives in one
# place. The CPU index serves e.g. 2.15.0+cpu, which then satisfies "torch==2.15.0" below.
RUN TORCH_PINS="$(grep -E '^(torch|torchvision)==' requirements/visual.txt | awk '{print $1}')" \
 && echo "installing CPU wheels: ${TORCH_PINS}" \
 && pip install ${TORCH_PINS} --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt

COPY . .

# Models are baked into /models at build time, so the container needs no network for them.
# data/ is a runtime volume and would hide anything stored under data/models, so models live
# outside it: MODELS_DIR overrides paths.models (core/config.py), HF_HOME holds e5.
# The assert fails the build if the override ever stops reaching the feature modules.
ENV MODELS_DIR=/models \
    DATA_DIR=/app/data \
    HF_HOME=/models/hf
RUN python -c "from fakecollector.core.config import make_context; from fakecollector.features import _media; d = _media.models_dir(make_context()); assert str(d) == '/models', d; print('models_dir =', d)" \
 && python docker/download_models.py

# Runtime defaults: offline (OSINT answers come from data/cache), no model downloads.
ENV OFFLINE=true \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TESSERACT_CMD=/usr/bin/tesseract \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Non-root user. compose passes the host UID/GID so files written into ./data stay yours.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app \
 && mkdir -p /app/data \
 && chown -R app:app /app/data /models
USER app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"

CMD ["streamlit", "run", "ui/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
