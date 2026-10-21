FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra elastic --extra bigquery
COPY src ./src
COPY ontology ./ontology
COPY data ./data
COPY docs ./docs
RUN uv sync --frozen --no-dev --extra elastic --extra bigquery
ENV PATH="/app/.venv/bin:$PATH" PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn ontology_agent_demo.api:app --host 0.0.0.0 --port ${PORT}"]
