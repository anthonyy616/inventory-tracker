"""
Webhook receiver for receipt service callbacks.

Place this file at: app/routers/webhooks.py in your inventory-tracking-system repo.

Register it in your main.py by adding:
    from app.routers import webhooks
    app.include_router(webhooks.router)

Environment variables required:
    RECEIPT_CALLBACK_SECRET — must match the receipt service's RECEIPT_CALLBACK_SECRET
"""

import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from supabase import create_client

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class ReceiptCallbackPayload(BaseModel):
    """Callback payload from the Receipt Generation Service."""
    order_reference: str  # The inventory order UUID echoed back
    receipt_id: str       # UUID of the receipt in the receipt service
    receipt_url: str      # Verification page URL or signed PDF URL
    status: str           # "completed" or "failed"
    error: Optional[str] = None  # Error message if status is "failed"


@router.post("/receipt-callback")
async def receipt_callback(payload: ReceiptCallbackPayload, request: Request):
    """
    Receive receipt generation completion callback from the Receipt Service.

    Validates the shared secret, then updates the order's receipt status.
    """
    # Verify shared secret
    webhook_secret = request.headers.get("X-Webhook-Secret")
    expected_secret = os.getenv("RECEIPT_CALLBACK_SECRET", "")

    if not expected_secret:
        raise HTTPException(
            status_code=500,
            detail="RECEIPT_CALLBACK_SECRET not configured"
        )

    if webhook_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # Connect to inventory Supabase
    sb = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
    )

    # Look up the order by order_reference (this is orders.id)
    order_result = sb.table("orders").select("id").eq(
        "id", payload.order_reference
    ).execute()

    if not order_result.data:
        raise HTTPException(
            status_code=404,
            detail=f"Order not found: {payload.order_reference}"
        )

    # Build update fields
    update_data = {
        "receipt_status": payload.status,
    }

    if payload.status == "completed":
        update_data["receipt_id"] = payload.receipt_id
        update_data["receipt_url"] = payload.receipt_url
    elif payload.status == "failed" and payload.error:
        update_data["receipt_error"] = payload.error

    # Update the order
    sb.table("orders").update(update_data).eq(
        "id", payload.order_reference
    ).execute()

    return JSONResponse(
        status_code=200,
        content={
            "message": "Callback processed",
            "order_id": payload.order_reference,
            "receipt_status": payload.status,
        },
    )
