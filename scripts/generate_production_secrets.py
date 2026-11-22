#!/usr/bin/env python3
"""
Generate cryptographically secure production secrets for the AI Web Agency Agent platform.
Usage:
    python scripts/generate_production_secrets.py
"""
import secrets
import sys

try:
    from passlib.hash import bcrypt
except ImportError:
    bcrypt = None


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

    if bcrypt:
        password = "admin" + secrets.token_hex(4)
        hashed = bcrypt.hash(password)
        print(f"\nGenerated Temporary Production Owner Password:")
        print(f"OWNER_EMAIL=owner@yourdomain.com")
        print(f"Temporary Password: {password}")
        print(f"OWNER_PASSWORD_HASH={hashed}")
    else:
        print("\nNote: install passlib[bcrypt] to generate OWNER_PASSWORD_HASH.")
    print("=" * 70)


if __name__ == "__main__":
    generate_secrets()
