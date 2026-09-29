"""Vercel entry point: every /api/* request is served by the FastAPI app."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shortlister.server import app  # noqa: E402,F401
