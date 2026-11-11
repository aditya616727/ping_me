"""Vercel serverless entry point - serves the FastAPI app from main.py."""
import os
import sys

# Make the project root importable so `import main` works on Vercel.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app  # noqa: E402,F401  (Vercel serves this ASGI `app`)
