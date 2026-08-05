"""
Aura Gateway Core - Production Native Email Service
===================================================
Dispatches emails via Google Gmail REST API using encrypted user refresh tokens.
Includes automatic token refreshment and error handling.
"""

import os
import base64
import logging
import httpx
from email.message import EmailMessage
from typing import Dict, Any, Optional
from app.core.security import decrypt_token

logger = logging.getLogger("email_service")


async def send_direct_email(
    recipient: str,
    subject: str,
    body: str,
    encrypted_refresh_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Dispatches an email via Google Gmail REST API using the user's decrypted refresh token.
    """
    if not encrypted_refresh_token:
        logger.error("❌ Dispatch failed: No Google refresh token available for user.")
        return {
            "status": "error",
            "message": "Gmail is not connected. Please connect your Gmail account in Workspace settings.",
            "mode": "google_oauth"
        }

    try:
        # Decrypt user's OAuth refresh token
        refresh_token = decrypt_token(encrypted_refresh_token)
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            logger.error("❌ Backend missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET.")
            return {
                "status": "error",
                "message": "Server OAuth credentials unconfigured.",
                "mode": "google_oauth"
            }

        # 1. Fetch short-lived Access Token
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            token_res = await client.post(token_url, data=token_data)
            
            if token_res.status_code != 200:
                logger.error(f"❌ OAuth Refresh Failed ({token_res.status_code}): {token_res.text}")
                return {
                    "status": "error",
                    "message": "Google authorization expired or revoked. Please re-connect Gmail.",
                    "mode": "google_oauth"
                }

            access_token = token_res.json().get("access_token")

        # 2. Build MIME Message & Encode to Base64URL
        msg = EmailMessage()
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.set_content(body)

        raw_bytes = msg.as_bytes()
        raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

        # 3. Post Message to Google Gmail REST API
        send_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            send_res = await client.post(send_url, json={"raw": raw_b64}, headers=headers)
            
            if send_res.status_code == 200:
                logger.info(f"✅ [GMAIL API SUCCESS] Sent to {recipient}")
                return {
                    "status": "success",
                    "message": f"Email successfully delivered to {recipient}.",
                    "mode": "google_oauth"
                }
            else:
                logger.error(f"❌ [GMAIL API ERROR] Send failed: {send_res.text}")
                return {
                    "status": "error",
                    "message": "Failed to deliver email through Gmail API.",
                    "mode": "google_oauth"
                }

    except Exception as exc:
        logger.error(f"❌ [OAUTH DISPATCH EXCEPTION] {exc}", exc_info=True)
        return {
            "status": "error",
            "message": f"Email dispatch failed: {str(exc)}",
            "mode": "google_oauth"
        }