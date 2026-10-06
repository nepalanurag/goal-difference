# Goal-difference ETL runtime. Python 3.12, pinned deps from etl/requirements.txt.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY etl/requirements.txt /app/etl/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/etl/requirements.txt

COPY etl /app/etl
COPY tests /app/tests
COPY dvc.yaml /app/dvc.yaml

# Default: validate the pipeline wiring without hitting the network.
CMD ["python", "-m", "pytest", "tests/", "-q"]
