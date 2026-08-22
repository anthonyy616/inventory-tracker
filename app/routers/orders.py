"""Orders management router - the core of the inventory tracking system."""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase import Client
import json

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

    return templates.TemplateResponse("orders/list.html", {"request": request, "orders": orders})


@router.get("/new", response_class=HTMLResponse)
async def new_order_form(request: Request):
    """Show form to create a new order."""
    supabase = get_supabase(request)

    products_result = supabase.table("products").select("id, name, sku, unit_price, quantity_in_stock, company_id, companies(name)").execute()
    products = products_result.data

    # Flatten company name on each product
    for p in products:
        p["company_name"] = p["companies"]["name"] if p.get("companies") else ""

    return templates.TemplateResponse("orders/form.html", {
        "request": request,
        "products": products,
        "order": None
    })


@router.post("/new")
async def create_order(
    request: Request,
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

    rpc_params = {
        "p_company_id": company_id,
        "p_customer_name": customer_name if customer_name else None,
        "p_items": items_data,
        "p_customer_email": customer_email if customer_email else None
    }

    try:
        result = supabase.rpc("create_order", rpc_params).execute()

        if result.data and result.data.get("success"):
            order_id = result.data["order_id"]
            return RedirectResponse(url=f"/orders/{order_id}", status_code=303)
        else:
            error_msg = result.data.get("error", "Unknown error") if result.data else "Failed to create order"
            raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        products_result = supabase.table("products").select("id, name, sku, unit_price, quantity_in_stock, company_id, companies(name)").execute()
        products = products_result.data
        for p in products:
            p["company_name"] = p["companies"]["name"] if p.get("companies") else ""

        return templates.TemplateResponse("orders/form.html", {
            "request": request,
            "products": products,
            "order": {"company_name": company_name, "customer_name": customer_name, "customer_email": customer_email},
            "error": str(e)
        })


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

    return templates.TemplateResponse("orders/detail.html", {
        "request": request,
        "order": order,
        "items": items
    })
