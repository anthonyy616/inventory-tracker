"""Products management router."""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase import Client

router = APIRouter(prefix="/products", tags=["products"])
templates = Jinja2Templates(directory="app/templates")


def get_supabase(request: Request) -> Client:
    """Get Supabase client from app state."""
    return request.app.state.supabase


def find_or_create_company(supabase: Client, company_name: str) -> str:
    """Find a company by name or create it. Returns the company_id."""
    result = supabase.table("companies").select("id").eq("name", company_name).limit(1).execute()
    if result.data:
        return result.data[0]["id"]
    # Create new company with just the name
    new = supabase.table("companies").insert({"name": company_name}).execute()
    return new.data[0]["id"]


@router.get("/", response_class=HTMLResponse)
async def list_products(request: Request):
    """List all products with company info."""
    supabase = get_supabase(request)
    result = supabase.table("products").select("*, companies(name)").order("created_at", desc=True).execute()
    products = result.data

    for product in products:
        product["company_name"] = product["companies"]["name"] if product.get("companies") else "Unknown"

    return templates.TemplateResponse("products/list.html", {"request": request, "products": products})


@router.get("/new", response_class=HTMLResponse)
async def new_product_form(request: Request):
    """Show form to create a new product."""
    return templates.TemplateResponse("products/form.html", {"request": request, "product": None})


@router.post("/new")
async def create_product(
    request: Request,
    company_name: str = Form(...),
    sku: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    unit_price: float = Form(...),
    quantity_in_stock: int = Form(0),
    reorder_threshold: int = Form(0)
):
    """Create a new product."""
    supabase = get_supabase(request)

    company_id = find_or_create_company(supabase, company_name.strip())

    product_data = {
        "company_id": company_id,
        "sku": sku,
        "name": name,
        "description": description,
        "unit_price": unit_price,
        "quantity_in_stock": quantity_in_stock,
        "reorder_threshold": reorder_threshold
    }

    result = supabase.table("products").insert(product_data).execute()

    if result.data:
        return RedirectResponse(url="/products", status_code=303)

    return templates.TemplateResponse("products/form.html", {
        "request": request,
        "product": {**product_data, "company_name": company_name},
        "error": "Failed to create product"
    })


@router.get("/{product_id}", response_class=HTMLResponse)
async def view_product(request: Request, product_id: str):
    """View product details with stock adjustment option."""
    supabase = get_supabase(request)
    result = supabase.table("products").select("*, companies(name)").eq("id", product_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")

    product = result.data[0]
    product["company_name"] = product["companies"]["name"] if product.get("companies") else "Unknown"

    transactions = supabase.table("inventory_transactions").select("*").eq("product_id", product_id).order("created_at", desc=True).limit(10).execute()

    return templates.TemplateResponse("products/detail.html", {
        "request": request,
        "product": product,
        "transactions": transactions.data
    })


@router.get("/{product_id}/edit", response_class=HTMLResponse)
async def edit_product_form(request: Request, product_id: str):
    """Show form to edit a product."""
    supabase = get_supabase(request)

    product_result = supabase.table("products").select("*, companies(name)").eq("id", product_id).execute()
    if not product_result.data:
        raise HTTPException(status_code=404, detail="Product not found")

    product = product_result.data[0]
    product["company_name"] = product["companies"]["name"] if product.get("companies") else ""

    return templates.TemplateResponse("products/form.html", {
        "request": request,
        "product": product
    })


@router.post("/{product_id}/edit")
async def update_product(
    request: Request,
    product_id: str,
    company_name: str = Form(...),
    sku: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    unit_price: float = Form(...),
    quantity_in_stock: int = Form(0),
    reorder_threshold: int = Form(0)
):
    """Update a product."""
    supabase = get_supabase(request)

    company_id = find_or_create_company(supabase, company_name.strip())

    product_data = {
        "company_id": company_id,
        "sku": sku,
        "name": name,
        "description": description,
        "unit_price": unit_price,
        "quantity_in_stock": quantity_in_stock,
        "reorder_threshold": reorder_threshold
    }

    result = supabase.table("products").update(product_data).eq("id", product_id).execute()

    if result.data:
        return RedirectResponse(url=f"/products/{product_id}", status_code=303)

    return templates.TemplateResponse("products/form.html", {
        "request": request,
        "product": {**product_data, "id": product_id, "company_name": company_name},
        "error": "Failed to update product"
    })


@router.post("/{product_id}/delete")
async def delete_product(request: Request, product_id: str):
    """Delete a product (only if no order items reference it)."""
    supabase = get_supabase(request)

    items_result = supabase.table("order_items").select("id").eq("product_id", product_id).limit(1).execute()

    if items_result.data:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete product: it has existing order items"
        )

    supabase.table("products").delete().eq("id", product_id).execute()

    return RedirectResponse(url="/products", status_code=303)


@router.post("/{product_id}/adjust-stock")
async def adjust_stock(
    request: Request,
    product_id: str,
    change_type: str = Form(...),
    quantity_change: int = Form(...)
):
    """Adjust stock for a product (restock or manual adjustment)."""
    supabase = get_supabase(request)

    product_result = supabase.table("products").select("*").eq("id", product_id).execute()
    if not product_result.data:
        raise HTTPException(status_code=404, detail="Product not found")

    product = product_result.data[0]
    current_stock = product["quantity_in_stock"]

    if change_type == "restock":
        new_quantity = current_stock + abs(quantity_change)
    elif change_type == "adjustment":
        new_quantity = current_stock + quantity_change
    else:
        raise HTTPException(status_code=400, detail="Invalid change type")

    if new_quantity < 0:
        raise HTTPException(status_code=400, detail="Stock cannot go below zero")

    rpc_params = {
        "p_product_id": product_id,
        "p_change_type": change_type,
        "p_quantity_change": quantity_change,
        "p_resulting_quantity": new_quantity
    }

    result = supabase.rpc("adjust_stock", rpc_params).execute()

    if result.data:
        return RedirectResponse(url=f"/products/{product_id}", status_code=303)

    raise HTTPException(status_code=500, detail="Failed to adjust stock")
