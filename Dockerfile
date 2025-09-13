FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd -r app && useradd -r -g app app

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY prompts /app/prompts

RUN pip install --upgrade pip && \
    pip install -e .

USER app

CMD ["python", "-m", "bot", "run", "--config", "/app/config.yaml"]

