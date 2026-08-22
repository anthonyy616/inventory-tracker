"""Transactions router for viewing inventory transaction log."""

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from supabase import Client
from typing import Optional

router = APIRouter(prefix="/transactions", tags=["transactions"])
templates = Jinja2Templates(directory="app/templates")


def get_supabase(request: Request) -> Client:
    """Get Supabase client from app state."""
    return request.app.state.supabase


@router.get("/", response_class=HTMLResponse)
async def list_transactions(
    request: Request,
    change_type: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None)
):
    """List all inventory transactions with filtering."""
    supabase = get_supabase(request)
    
    # Build query
    query = supabase.table("inventory_transactions").select("*, products(name, sku)")
    
    # Apply filters
    if change_type:
        query = query.eq("change_type", change_type)
    
    if start_date:
        query = query.gte("created_at", start_date)
    
    if end_date:
        query = query.lte("created_at", end_date + "T23:59:59")
    
    # Execute query
    result = query.order("created_at", desc=True).limit(100).execute()
    transactions = result.data
    
    # Flatten product info
    for tx in transactions:
        if tx.get("products"):
            tx["product_name"] = tx["products"]["name"]
            tx["product_sku"] = tx["products"]["sku"]
        else:
            tx["product_name"] = "Unknown"
            tx["product_sku"] = "-"
        
        # Get order number if order_id exists
        if tx.get("order_id"):
            order_result = supabase.table("orders").select("order_number").eq("id", tx["order_id"]).execute()
            if order_result.data:
                tx["order_number"] = order_result.data[0]["order_number"]
            else:
                tx["order_number"] = "-"
        else:
            tx["order_number"] = "-"
    
    return templates.TemplateResponse("transactions/list.html", {
        "request": request,
        "transactions": transactions,
        "change_type": change_type,
        "start_date": start_date,
        "end_date": end_date
    })
