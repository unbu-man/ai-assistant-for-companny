FROM python:3.13-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[mvp]" && useradd --system --no-create-home assistant
USER assistant
CMD ["uvicorn", "company_ai.mvp.app:app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8765", "--no-access-log"]
