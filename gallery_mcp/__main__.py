"""Entry point: python -m gallery_mcp"""
import uvicorn

from gallery_mcp.config import settings
from gallery_mcp.server import build_app

if __name__ == "__main__":
    uvicorn.run(build_app(), host=settings.MCP_HOST, port=settings.MCP_PORT, loop="asyncio")
