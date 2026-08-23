"""Orders management router - the core of the inventory tracking system."""

from fastapi import APIRouter, Request, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from supabase import Client
import json
import os
import asyncio
import httpx

router = APIRouter(prefix="/orders", tags=["orders"])
templates = Jinja2Templates(directory="app/templates")


def get_supabase(request: Request) -> Client:
    """Get Supabase client from app state."""
    return request.app.state.supabase


def find_or_create_company(supabase: Client, company_name: str) -> str:
    """Find a company by name or create it. Returns the company_id."""
    result = supabase.table("companies").select("id").eq("name", company_name).limit(1).execute()
    if result.data:
        return result.data[0]["id"]
    new = supabase.table("companies").insert({"name": company_name}).execute()
    return new.data[0]["id"]


@router.get("/", response_class=HTMLResponse)
async def list_orders(request: Request):
    """List all orders with company info."""
    supabase = get_supabase(request)
    result = supabase.table("orders").select("*, companies(name)").order("created_at", desc=True).execute()
    orders = result.data

    for order in orders:
        order["company_name"] = order["companies"]["name"] if order.get("companies") else "Unknown"

    return templates.TemplateResponse(request, "orders/list.html", {"orders": orders})


@router.get("/new", response_class=HTMLResponse)
async def new_order_form(request: Request):
    """Show form to create a new order."""
    supabase = get_supabase(request)

    products_result = supabase.table("products").select("id, name, sku, unit_price, quantity_in_stock, company_id, companies(name)").execute()
    products = products_result.data

    # Flatten company name on each product
    for p in products:
        p["company_name"] = p["companies"]["name"] if p.get("companies") else ""

    return templates.TemplateResponse(request, "orders/form.html", {
        "products": products,
        "order": None
    })


@router.post("/new")
async def create_order(
    request: Request,
    background_tasks: BackgroundTasks,
    company_name: str = Form(...),
    customer_name: str = Form(""),
    customer_email: str = Form(""),
    items: str = Form(...)
):
    """Create a new order - calls the atomic create_order RPC."""
    supabase = get_supabase(request)

    try:
        items_data = json.loads(items)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid items format")

    if not items_data:
        raise HTTPException(status_code=400, detail="No items provided")

    # Resolve company name to id (create if needed)
    company_id = find_or_create_company(supabase, company_name.strip())

    receipt_client_id = os.getenv("RECEIPT_SERVICE_CLIENT_ID", "")

    rpc_params = {
        "p_company_id": company_id,
        "p_customer_name": customer_name if customer_name else None,
        "p_items": items_data,
        "p_customer_email": customer_email if customer_email else None,
        "p_receipt_client_id": receipt_client_id if receipt_client_id else None
    }

    try:
        result = supabase.rpc("create_order", rpc_params).execute()

        if result.data and result.data.get("success"):
            order_id = result.data["order_id"]

            # Notify receipt service directly (replaces Supabase Database Webhook)
            receipt_service_url = os.getenv("RECEIPT_SERVICE_URL", "http://localhost:8001")
            webhook_secret = os.getenv("INVENTORY_WEBHOOK_SECRET", "")
            if receipt_client_id and webhook_secret:
                # Fetch the outbox row we just created
                outbox = supabase.table("receipt_requests").select("payload").eq("order_id", order_id).limit(1).execute()
                if outbox.data:
                    background_tasks.add_task(
                        send_to_receipt_service,
                        receipt_service_url,
                        webhook_secret,
                        outbox.data[0]["payload"],
                    )

            return RedirectResponse(url=f"/orders/{order_id}", status_code=303)
        else:
            error_msg = result.data.get("error", "Unknown error") if result.data else "Failed to create order"
            raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        products_result = supabase.table("products").select("id, name, sku, unit_price, quantity_in_stock, company_id, companies(name)").execute()
        products = products_result.data
        for p in products:
            p["company_name"] = p["companies"]["name"] if p.get("companies") else ""

        return templates.TemplateResponse(request, "orders/form.html", {
            "products": products,
            "order": {"company_name": company_name, "customer_name": customer_name, "customer_email": customer_email},
            "error": str(e)
        })


async def send_to_receipt_service(receipt_service_url: str, webhook_secret: str, payload: dict):
    """Background task: POST the outbox payload to the receipt service with retry."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{receipt_service_url}/webhooks/inventory-order",
                    json={"type": "INSERT", "table": "receipt_requests", "record": {"payload": payload}},
                    headers={"X-Inventory-Webhook-Secret": webhook_secret},
                )
                if resp.status_code < 500:
                    print(f"[receipt] Sent to receipt service: {resp.status_code}")
                    return
                print(f"[receipt] Server error {resp.status_code}, attempt {attempt + 1}/{max_retries}")
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            print(f"[receipt] Connection error on attempt {attempt + 1}/{max_retries}: {e}")
        except Exception as e:
            print(f"[receipt] Unexpected error on attempt {attempt + 1}/{max_retries}: {e}")
        if attempt < max_retries - 1:
            wait = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
            print(f"[receipt] Retrying in {wait}s...")
            await asyncio.sleep(wait)
    print(f"[receipt] Failed to notify receipt service after {max_retries} attempts")


@router.get("/{order_id}", response_class=HTMLResponse)
async def view_order(request: Request, order_id: str):
    """View order details with line items."""
    supabase = get_supabase(request)

    order_result = supabase.table("orders").select("*, companies(name)").eq("id", order_id).execute()

    if not order_result.data:
        raise HTTPException(status_code=404, detail="Order not found")

    order = order_result.data[0]
    order["company_name"] = order["companies"]["name"] if order.get("companies") else "Unknown"

    items_result = supabase.table("order_items").select("*, products(name)").eq("order_id", order_id).execute()
    items = items_result.data

    for item in items:
        item["product_name"] = item["products"]["name"] if item.get("products") else item.get("product_name_snapshot", "Unknown")

    return templates.TemplateResponse(request, "orders/detail.html", {
        "order": order,
        "items": items
    })


@router.post("/{order_id}/delete")
async def delete_order(request: Request, order_id: str):
    """Delete an order and restore stock levels."""
    supabase = get_supabase(request)

    # Verify order exists
    order_result = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not order_result.data:
        raise HTTPException(status_code=404, detail="Order not found")

    order = order_result.data[0]

    # Restore stock for each item
    items_result = supabase.table("order_items").select("product_id, quantity").eq("order_id", order_id).execute()
    for item in (items_result.data or []):
        supabase.table("products").update(
            {"quantity_in_stock": supabase.table("products").select("quantity_in_stock").eq("id", item["product_id"]).execute().data[0]["quantity_in_stock"] + item["quantity"]}
        ).eq("id", item["product_id"]).execute()

    # Delete related records
    supabase.table("order_items").delete().eq("order_id", order_id).execute()
    supabase.table("inventory_transactions").delete().eq("order_id", order_id).execute()
    supabase.table("receipt_requests").delete().eq("order_id", order_id).execute()
    supabase.table("orders").delete().eq("id", order_id).execute()

    return RedirectResponse(url="/orders", status_code=303)


@router.get("/{order_id}/receipt/view")
async def view_receipt(request: Request, order_id: str):
    """Proxy the receipt PDF for inline display (avoids CORS issues with signed URLs)."""
    supabase = get_supabase(request)

    order_result = supabase.table("orders").select("receipt_url, order_number, receipt_id").eq("id", order_id).execute()
    if not order_result.data or not order_result.data[0].get("receipt_url"):
        raise HTTPException(status_code=404, detail="Receipt not available")

    receipt_url = order_result.data[0]["receipt_url"]
    order_number = order_result.data[0].get("order_number", order_id[:8])

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(receipt_url)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch receipt")

        content_type = resp.headers.get("content-type", "")
        if "pdf" not in content_type and not resp.content[:5] == b"%PDF-":
            raise HTTPException(status_code=502, detail="Receipt URL did not return a PDF")

    return StreamingResponse(
        iter([resp.content]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=receipt-{order_number}.pdf",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/{order_id}/receipt/download")
async def download_receipt(request: Request, order_id: str):
    """Download the receipt PDF as a file attachment."""
    supabase = get_supabase(request)

    order_result = supabase.table("orders").select("receipt_url, order_number, receipt_id").eq("id", order_id).execute()
    if not order_result.data or not order_result.data[0].get("receipt_url"):
        raise HTTPException(status_code=404, detail="Receipt not available")

    receipt_url = order_result.data[0]["receipt_url"]
    order_number = order_result.data[0].get("order_number", order_id[:8])

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(receipt_url)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch receipt")

        content_type = resp.headers.get("content-type", "")
        if "pdf" not in content_type and not resp.content[:5] == b"%PDF-":
            raise HTTPException(status_code=502, detail="Receipt URL did not return a PDF")

    return StreamingResponse(
        iter([resp.content]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=receipt-{order_number}.pdf",
        },
    )
