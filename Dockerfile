# GRS Telemetry Decoder — raw packets -> NGHam -> telemetria do FS-2.
#
# Sem gcc e sem libpq-dev: pyngham é Python puro, e psycopg2-BINARY vem de
# wheel manylinux no CPython 3.11 — o mesmo argumento do grs-iq-recorder.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e .

EXPOSE 5592

CMD ["python", "-m", "telemetry_decoder.main", "serve"]
