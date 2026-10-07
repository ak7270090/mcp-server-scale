FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml ./
COPY proto ./proto
COPY src ./src
RUN pip install grpcio-tools \
    && python -m grpc_tools.protoc -I proto --python_out=src --grpc_python_out=src \
       proto/inventory/v1/inventory.proto \
    && pip install . \
    && pip uninstall -y grpcio-tools \
    && useradd --create-home inventoryuser

USER inventoryuser
EXPOSE 50051
CMD ["python", "-m", "inventoryservice"]
