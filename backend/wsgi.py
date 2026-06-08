"""Gunicorn entry point.
Usage: gunicorn --bind 0.0.0.0:8000 --workers 4 backend.wsgi:app
"""
from backend.main import app
