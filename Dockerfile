# syntax=docker/dockerfile:1

FROM python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b AS common

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md requirements.lock ./
COPY src ./src

RUN python -m pip install --no-cache-dir --requirement requirements.lock \
    && python -m pip install --no-cache-dir --no-deps .

FROM common AS test

COPY requirements-test.lock ./
RUN python -m pip install --no-cache-dir --requirement requirements-test.lock
COPY runner.sh ./runner.sh
COPY tests ./tests
RUN python -m pytest

FROM common AS runtime

RUN addgroup --system appgroup \
    && adduser --system --uid 10001 --ingroup appgroup --home /home/appuser appuser \
    && mkdir /output \
    && chown appuser:appgroup /output

USER appuser

ENTRYPOINT ["actions-scan"]
