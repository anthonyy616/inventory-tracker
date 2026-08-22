"""Inventory Tracking System - Main entry point."""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
import os

from app.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
from app.routers import companies, products, orders, transactions, webhooks

app = FastAPI(title="Inventory Tracking System")

# CORS middleware (allow all for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="app/templates")

# Supabase client (server-side only, service role key)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Store supabase client in app state for routers to access
app.state.supabase = supabase

# Include routers
app.include_router(companies.router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(transactions.router)
app.include_router(webhooks.router)


@app.get("/health")
async def health_check():
    """Health check endpoint - confirms Supabase connection works."""
    try:
        # Simple query to verify connection
        result = supabase.table("companies").select("id").limit(1).execute()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}, 503


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root page - redirects to dashboard or products."""
    return templates.TemplateResponse(request, "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
