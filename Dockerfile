FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Create non-root user before copying so we can chown in COPY (one layer).
RUN useradd --create-home --shell /bin/bash --uid 10001 appuser

COPY --chown=appuser:appuser pyproject.toml README.md ./
COPY --chown=appuser:appuser srg_mcp/ ./srg_mcp/

RUN pip install ".[server]"

USER appuser

EXPOSE 8090
ENV PORT=8090

CMD ["srgplus-mcp-serve"]
