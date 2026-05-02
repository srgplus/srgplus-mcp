FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY srg_mcp/ ./srg_mcp/

RUN pip install ".[server]"

EXPOSE 8090
ENV PORT=8090

CMD ["srgplus-mcp-serve"]
