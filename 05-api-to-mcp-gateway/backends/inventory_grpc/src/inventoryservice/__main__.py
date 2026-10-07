"""Entry point: ``python -m inventoryservice`` serves gRPC on port 50051."""

import asyncio

from inventoryservice.server import serve

if __name__ == "__main__":
    asyncio.run(serve())
