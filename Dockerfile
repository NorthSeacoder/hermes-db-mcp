FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache .

FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/hermes-db-mcp /usr/local/bin/hermes-db-mcp
COPY src/ src/

ENV TRANSPORT=sse
EXPOSE 8080

ENTRYPOINT ["hermes-db-mcp"]
