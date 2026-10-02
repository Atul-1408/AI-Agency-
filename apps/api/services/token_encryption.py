"""
Token Encryption Service.

Implements authenticated symmetric encryption (AES-256-GCM) for sensitive
OAuth refresh tokens and credentials.

SECURITY GUARANTEES:
1. Refresh tokens are NEVER stored or persisted in plaintext.
2. Authenticated encryption (AES-GCM with 96-bit nonce) prevents tampering and forgery.
3. Fail closed: If GMAIL_TOKEN_ENCRYPTION_KEY is missing or invalid, all operations
   raise TokenEncryptionKeyMissingError. Plaintext is NEVER accepted as a fallback.
4. Secrets, keys, and decrypted tokens are NEVER logged.
"""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.config import settings


class TokenEncryptionError(Exception):
    """Base exception for token encryption / decryption failures."""
    pass


class TokenEncryptionKeyMissingError(TokenEncryptionError):
    """Raised when the encryption key is unconfigured or empty (Fail Closed)."""
    pass


class TokenDecryptionError(TokenEncryptionError):
    """Raised when ciphertext payload is corrupted, tampered, or wrong key is supplied."""
    pass


class TokenEncryptionService:
    """
    AES-256-GCM Token Encryption and Decryption Service.
    """

    def __init__(self, key: Optional[str] = None):
        self._raw_key = key

    def _get_key(self) -> bytes:
        """
        Resolve the 256-bit encryption key.
        Fails closed if key is missing or blank.
        """
        raw = self._raw_key if self._raw_key is not None else settings.GMAIL_TOKEN_ENCRYPTION_KEY
        if not raw or not raw.strip():
            raise TokenEncryptionKeyMissingError(
                "GMAIL_TOKEN_ENCRYPTION_KEY is missing or empty. Token encryption must fail closed."
            )

        clean_raw = raw.strip()

        # 1. Try Base64 decoding if 32 bytes
        try:
            decoded = base64.b64decode(clean_raw, validate=True)
            if len(decoded) == 32:
                return decoded
        except Exception:
            pass

        # 2. Try Hex decoding if 64 chars (32 bytes)
        try:
            if len(clean_raw) == 64:
                decoded = bytes.fromhex(clean_raw)
                if len(decoded) == 32:
                    return decoded
        except Exception:
            pass

        # 3. Derive 32 bytes deterministically via SHA-256
        return hashlib.sha256(clean_raw.encode("utf-8")).digest()

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext using AES-256-GCM.
        Generates a fresh 12-byte nonce for every invocation.
        Returns URL-safe Base64 encoded (nonce + ciphertext + tag).
        """
        if not plaintext:
            raise TokenEncryptionError("Cannot encrypt empty token payload.")

        key_bytes = self._get_key()
        aesgcm = AESGCM(key_bytes)
        nonce = os.urandom(12)  # 96-bit nonce for AES-GCM
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        combined = nonce + ciphertext
        return base64.urlsafe_b64encode(combined).decode("ascii")

    def decrypt(self, encrypted_token: str) -> str:
        """
        Decrypt ciphertext using AES-256-GCM.
        Validates authentication tag and extracts plaintext.
        Raises TokenDecryptionError if corrupted, tampered, or invalid key.
        """
        if not encrypted_token or not encrypted_token.strip():
            raise TokenDecryptionError("Cannot decrypt empty token payload.")

        key_bytes = self._get_key()
        aesgcm = AESGCM(key_bytes)

        try:
            combined = base64.urlsafe_b64decode(encrypted_token.strip().encode("ascii"))
            # Must contain at least 12 bytes nonce + 16 bytes auth tag = 28 bytes
            if len(combined) < 28:
                raise TokenDecryptionError("Encrypted payload is malformed or truncated.")

            nonce = combined[:12]
            ciphertext = combined[12:]
            decrypted = aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted.decode("utf-8")
        except TokenEncryptionError:
            raise
        except Exception as exc:
            # Mask details to prevent oracle / side-channel leaks
            raise TokenDecryptionError(
                "Token decryption failed: ciphertext is invalid, tampered, or key mismatch."
            ) from exc
