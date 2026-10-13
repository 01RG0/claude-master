"""brain/api/__init__.py — Unified Backend API for claude-master.
"""

from brain.api.app import create_app
from brain.api.security import get_or_create_auth_token, verify_token, mask_key, hash_key

__all__ = ["create_app", "get_or_create_auth_token", "verify_token", "mask_key", "hash_key"]
