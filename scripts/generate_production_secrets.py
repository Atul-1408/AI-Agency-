#!/usr/bin/env python3
"""
Generate cryptographically secure production secrets for the AI Web Agency Agent platform.
Compatible with all Python versions and bcrypt >= 4.0.0.
Usage:
    python scripts/generate_production_secrets.py
"""
import secrets
import sys


def hash_password(password: str) -> str:
    """Hash password using native bcrypt (preferred) or passlib fallback."""
    # 1. Native bcrypt library (recommended, no passlib wrap bug)
    try:
        import bcrypt
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
    except (ImportError, Exception):
        pass

    # 2. Passlib fallback
    try:
        from passlib.hash import bcrypt as passlib_bcrypt
        return passlib_bcrypt.hash(password)
    except Exception:
        pass

    return ""


def generate_secrets():
    app_secret = secrets.token_hex(32)         # 64-char hex string
    nextauth_secret = secrets.token_hex(32)    # 64-char hex string
    gmail_key = secrets.token_urlsafe(32)      # 32-byte urlsafe base64 string
    deploy_key = secrets.token_urlsafe(32)     # 32-byte urlsafe base64 string

    print("=" * 70)
    print("  AI Web Agency Agent — Production Secrets Generator")
    print("=" * 70)
    print("\nCopy and paste these values into your production .env or cloud environment:")
    print("-" * 70)
    print(f"APP_ENV=production")
    print(f"APP_SECRET={app_secret}")
    print(f"NEXTAUTH_SECRET={nextauth_secret}")
    print(f"GMAIL_TOKEN_ENCRYPTION_KEY={gmail_key}")
    print(f"DEPLOYMENT_TOKEN_ENCRYPTION_KEY={deploy_key}")
    print("-" * 70)

    password = "Admin@" + secrets.token_hex(4)
    hashed = hash_password(password)

    print("\nGenerated Owner Credentials:")
    print(f"OWNER_EMAIL=owner@yourdomain.com")
    print(f"Temporary Password: {password}")
    if hashed:
        print(f"OWNER_PASSWORD_HASH={hashed}")
    else:
        print("OWNER_PASSWORD_HASH= (Note: run in venv with 'pip install bcrypt' to generate hash)")
    print("=" * 70)


if __name__ == "__main__":
    generate_secrets()
