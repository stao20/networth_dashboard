"""Fernet helpers for provider credential storage."""
from __future__ import annotations

import os

from cryptography.fernet import Fernet


def load_fernet_key() -> bytes:
    raw = os.environ.get("SYNC_CREDENTIALS_KEY")
    if not raw:
        # Streamlit secrets fallback for interactive app
        try:
            import streamlit as st

            raw = st.secrets.get("sync", {}).get("credentials_key")
        except Exception:
            raw = None
    if not raw:
        raise RuntimeError(
            "SYNC_CREDENTIALS_KEY env var (or secrets.sync.credentials_key) is required"
        )
    return raw.encode() if isinstance(raw, str) else raw


def encrypt_secret(plaintext: str, key: bytes | None = None) -> str:
    f = Fernet(key or load_fernet_key())
    return f.encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str, key: bytes | None = None) -> str:
    f = Fernet(key or load_fernet_key())
    return f.decrypt(token.encode()).decode()
