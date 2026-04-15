# app/services/crypto.py
"""
Fernet encryption for storing OAuth tokens at rest in MongoDB.
"""

import base64
import hashlib

from cryptography.fernet import Fernet

from app.config import get_settings


def _get_fernet() -> Fernet:
    """Derive a Fernet key from the session_secret setting."""
    secret = get_settings().session_secret.encode()
    # Fernet requires a 32-byte url-safe base64 key; derive one via SHA-256.
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token string, returning a UTF-8 ciphertext string."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a ciphertext string back to the original token."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
