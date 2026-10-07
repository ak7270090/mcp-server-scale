FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install . && useradd --create-home ordersuser

USER ordersuser
EXPOSE 8001
CMD ["uvicorn", "ordersapi.app:create_orders_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]
