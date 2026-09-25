"""Cloudflare Worker entry point; the product routes remain in app.py."""

from app import app
from workers import wsgi


Default = wsgi.entrypoint(app)
