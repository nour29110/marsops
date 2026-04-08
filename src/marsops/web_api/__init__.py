"""MarsOps Web API package.

Provides a FastAPI-based HTTP adapter over the same inner functions used by
the MCP server.  The package consists of three modules:

* :mod:`~marsops.web_api.parser`  — deterministic natural-language command parser.
* :mod:`~marsops.web_api.events`  — in-memory telemetry pub/sub broadcaster.
* :mod:`~marsops.web_api.app`     — FastAPI application with REST and WebSocket endpoints.
"""
