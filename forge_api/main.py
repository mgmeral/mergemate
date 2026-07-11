"""
forge_api/main.py

Entry point for running the MergeMate API server with uvicorn.

Environment variables:
    MERGEMATE_DB_PATH       Path to the SQLite database (default: mergemate.db)
    MERGEMATE_WORKER_IMAGE  Docker image for the worker (default: mergemate-worker:latest)
    MERGEMATE_SSH_KEY_PATH  Path to SSH key (default: ~/.ssh/id_rsa)
"""

from __future__ import annotations

import os

import uvicorn

from forge_api.app import create_app

# Create the application using environment variables for configuration
app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
