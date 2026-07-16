"""Pytest configuration — ensures src is importable."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("NVIDIA_NIM_API_KEY", "test")
os.environ.setdefault("AUTH_SECRET_KEY", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
