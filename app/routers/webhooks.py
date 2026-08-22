"""Webhooks router for receiving receipt callbacks from the Receipt Generation Service."""

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import os

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class ReceiptCallback(BaseModel):
    """Callback payload from Receipt Generation Service."""
    order_reference: str
    receipt_id: str
    receipt_url: str
    status: str  # completed or failed
    error: Optional[str] = None


@router.post("/receipt-callback")
async def receipt_callback(
    request: Request,
    callback: ReceiptCallback,
    x_webhook_secret: Optional[str] = Header(None)
):
    """
    Receive receipt generation callback from Receipt Service.
    
    This endpoint updates the order's receipt_status based on the callback.
    It requires a shared secret in the X-Webhook-Secret header.
    """
    # Verify shared secret
    expected_secret = os.getenv("RECEIPT_CALLBACK_SECRET")
    if not expected_secret:
        raise HTTPException(status_code=500, detail="RECEIPT_CALLBACK_SECRET not configured")
    
    if x_webhook_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    
    # Get Supabase client
    supabase = request.app.state.supabase
    
    # Find the order by order_reference (which is the order_id)
    order_result = supabase.table("orders").select("*").eq("id", callback.order_reference).execute()
    
    if not order_result.data:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order = order_result.data[0]
    
    # Update order based on callback status
    update_data = {
        "receipt_status": callback.status,
        "receipt_id": callback.receipt_id,
        "receipt_url": callback.receipt_url
    }
    
    if callback.status == "failed" and callback.error:
        update_data["receipt_error"] = callback.error
    
    # Perform the update
    result = supabase.table("orders").update(update_data).eq("id", callback.order_reference).execute()
    
    if result.data:
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"Order {callback.order_reference} updated with receipt status: {callback.status}"
            }
        )
    else:
        raise HTTPException(status_code=500, detail="Failed to update order")
