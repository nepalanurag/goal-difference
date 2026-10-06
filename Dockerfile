# Goal-difference ETL runtime (phase 9.5 reproducibility).
# Pinned env for CI/training parity: the same image runs refresh locally
# and in CI, so "works on my machine" failures surface before merge.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Deps first so layer caching survives code changes.
COPY etl/requirements.txt /app/etl/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/etl/requirements.txt

# The repo. .dockerignore keeps images and build junk out; secrets stay
# out of the image (API_FOOTBALL_KEY is passed at runtime via env).
COPY . /app

# Default: the same refresh the daily GitHub Action runs (hash-gated:
# exits quietly when fixtures are unchanged). Override at runtime, e.g.
# `docker run gd python -m pytest tests/ -q`.
ENTRYPOINT ["python", "-m", "etl.refresh"]
