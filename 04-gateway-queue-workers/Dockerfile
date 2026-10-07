FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install . && useradd --create-home mcpuser

USER mcpuser
EXPOSE 8000
# One image for all three services; compose sets the command per service.
CMD ["python", "-m", "mcpqueue.gateway"]
