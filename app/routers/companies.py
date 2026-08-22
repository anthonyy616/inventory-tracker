"""Companies management router."""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase import Client

router = APIRouter(prefix="/companies", tags=["companies"])
templates = Jinja2Templates(directory="app/templates")


def get_supabase(request: Request) -> Client:
    """Get Supabase client from app state."""
    return request.app.state.supabase


@router.get("/", response_class=HTMLResponse)
async def list_companies(request: Request):
    """List all companies."""
    supabase = get_supabase(request)
    result = supabase.table("companies").select("*").order("created_at", desc=True).execute()
    companies = result.data
    return templates.TemplateResponse("companies/list.html", {"request": request, "companies": companies})


@router.get("/new", response_class=HTMLResponse)
async def new_company_form(request: Request):
    """Show form to create a new company."""
    return templates.TemplateResponse("companies/form.html", {"request": request, "company": None})


@router.post("/new")
async def create_company(
    request: Request,
    name: str = Form(...),
    address: str = Form(""),
    contact_info: str = Form(""),
    logo_url: str = Form("")
):
    """Create a new company."""
    supabase = get_supabase(request)
    
    company_data = {
        "name": name,
        "address": address,
        "contact_info": contact_info,
        "logo_url": logo_url
    }
    
    result = supabase.table("companies").insert(company_data).execute()
    
    if result.data:
        return RedirectResponse(url="/companies", status_code=303)
    
    return templates.TemplateResponse("companies/form.html", {
        "request": request,
        "company": company_data,
        "error": "Failed to create company"
    })


@router.get("/{company_id}", response_class=HTMLResponse)
async def view_company(request: Request, company_id: str):
    """View company details."""
    supabase = get_supabase(request)
    result = supabase.table("companies").select("*").eq("id", company_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Company not found")
    
    company = result.data[0]
    return templates.TemplateResponse("companies/detail.html", {"request": request, "company": company})


@router.get("/{company_id}/edit", response_class=HTMLResponse)
async def edit_company_form(request: Request, company_id: str):
    """Show form to edit a company."""
    supabase = get_supabase(request)
    result = supabase.table("companies").select("*").eq("id", company_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Company not found")
    
    company = result.data[0]
    return templates.TemplateResponse("companies/form.html", {"request": request, "company": company})


@router.post("/{company_id}/edit")
async def update_company(
    request: Request,
    company_id: str,
    name: str = Form(...),
    address: str = Form(""),
    contact_info: str = Form(""),
    logo_url: str = Form("")
):
    """Update a company."""
    supabase = get_supabase(request)
    
    company_data = {
        "name": name,
        "address": address,
        "contact_info": contact_info,
        "logo_url": logo_url
    }
    
    result = supabase.table("companies").update(company_data).eq("id", company_id).execute()
    
    if result.data:
        return RedirectResponse(url=f"/companies/{company_id}", status_code=303)
    
    return templates.TemplateResponse("companies/form.html", {
        "request": request,
        "company": {**company_data, "id": company_id},
        "error": "Failed to update company"
    })
