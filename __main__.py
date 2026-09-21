"""MCP server entry point."""
import atexit
import inspect
import sys
from pathlib import Path

# Add package directory to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from server import mcp, startup, shutdown


def main():
    """Run the MCP server over stdio."""
    startup()
    atexit.register(shutdown)
    if hasattr(mcp, "run"):
        sig = inspect.signature(mcp.run)
        if "transport" in sig.parameters:
            mcp.run(transport="stdio")
        else:
            mcp.run()
    else:
        raise RuntimeError("MCP server instance has no run method")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        shutdown()
        sys.exit(0)
