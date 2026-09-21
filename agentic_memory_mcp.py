"""Module entry point for ``python -m agentic_memory_mcp``."""
import atexit
import inspect

from server import mcp, shutdown, startup


def main() -> None:
    """Run the MCP server over stdio."""
    startup()
    atexit.register(shutdown)
    if not hasattr(mcp, "run"):
        raise RuntimeError("MCP server instance has no run method")

    if "transport" in inspect.signature(mcp.run).parameters:
        mcp.run(transport="stdio")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
