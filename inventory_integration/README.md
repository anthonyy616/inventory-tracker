# Inventory System — Receipt Service Integration

This folder contains everything you need to add to your **inventory-tracking-system** repo to receive receipt callbacks from the Receipt Generation Service.

---

## What you're adding

The Receipt Service generates receipts asynchronously. When it finishes (success or failure), it POSTs a callback to your inventory system so you can update the order's `receipt_status`, `receipt_id`, and `receipt_url`. This is the return trip of the outbox pattern — the only way the two systems communicate.

---

## Files to add to your inventory repo

### 1. `app/routers/webhooks.py` — Callback receiver endpoint

**Where:** Copy this file into your inventory-tracking-system repo at `app/routers/webhooks.py`.

**What it does:**
- Exposes `POST /webhooks/receipt-callback`
- Validates a shared secret via `X-Webhook-Secret` header
- Updates the order's `receipt_status`, `receipt_id`, `receipt_url`, and `receipt_error`
- Returns 200 on success

### 2. Register the router in your `main.py`

Add these two lines to your inventory system's `main.py`:

```python
from app.routers import webhooks

app.include_router(webhooks.router)
```

Place them near your other `app.include_router(...)` calls.

### 3. Add env vars to your inventory system's `.env`

```env
# Callback secret — MUST match RECEIPT_CALLBACK_SECRET in the receipt service's .env
RECEIPT_CALLBACK_SECRET=your-shared-secret-here

# The client ID assigned to your inventory business in the receipt service
# (get this from the receipt service's /clients admin page after registering)
RECEIPT_SERVICE_CLIENT_ID=your-receipt-service-client-uuid
```

**Important:** The `RECEIPT_CALLBACK_SECRET` value must be **identical** in both projects' `.env` files.

### 4. (Optional) Add receipt_error to orders table

If your inventory Supabase DB doesn't already have the `receipt_error` column on `orders`, run this SQL in your inventory Supabase SQL Editor:

```sql
ALTER TABLE orders ADD COLUMN IF NOT EXISTS receipt_error TEXT;
CREATE INDEX IF NOT EXISTS idx_orders_receipt_status ON orders(receipt_status);
```

This is already in `migrations/legacy_inventory_system/002_add_receipt_error_column.sql`.

### 5. Update order detail page (optional but recommended)

If your order detail page template shows order info, add receipt status display:

```html
<!-- In your order detail template -->
<div class="receipt-status">
    <strong>Receipt Status:</strong>
    {% if order.receipt_status == 'completed' %}
        <span class="badge badge-success">✅ Completed</span>
        {% if order.receipt_url %}
        <a href="{{ order.receipt_url }}" target="_blank" class="btn btn-secondary">View Receipt</a>
        {% endif %}
    {% elif order.receipt_status == 'failed' %}
        <span class="badge badge-danger">❌ Failed</span>
        {% if order.receipt_error %}
        <p class="error-detail">{{ order.receipt_error }}</p>
        {% endif %}
    {% else %}
        <span class="badge badge-warning">⏳ Pending</span>
    {% endif %}
</div>
```

---

## Setup the Supabase Database Webhook (inventory side)

This is configured in the **Inventory** system's Supabase dashboard, NOT in code:

1. Go to your **Inventory Supabase project** → Database → Webhooks
2. Click **Create a new webhook**
3. Configure:
   - **Name:** `receipt-request-to-receipt-service`
   - **Table:** `receipt_requests`
   - **Event:** `INSERT`
   - **Type:** HTTP request
   - **Method:** POST
   - **URL:** `http://localhost:8001/webhooks/inventory-order` (or your receipt service's deployed URL)
   - **Timeout:** 10 seconds
4. Add a header:
   - **Key:** `X-Inventory-Webhook-Secret`
   - **Value:** the same value as `INVENTORY_WEBHOOK_SECRET` in the receipt service's `.env`
5. Save and **enable** the webhook

**For local development:** If both services run on localhost, use `http://localhost:8001/webhooks/inventory-order` as the webhook URL. Supabase webhooks need a publicly reachable URL, so for local dev you'll need a tunnel like ngrok:
```bash
ngrok http 8001
# Use the https URL from ngrok in the webhook config
```

---

## End-to-end flow after setup

1. User places an order in the Inventory system
2. `create_order` RPC atomically creates order + outbox row in `receipt_requests`
3. Supabase Database Webhook fires on the `receipt_requests` INSERT
4. Webhook POSTs to Receipt Service's `/webhooks/inventory-order`
5. Receipt Service generates PDF, stores it, emails it, sends callback
6. Callback hits Inventory's `POST /webhooks/receipt-callback`
7. Order's `receipt_status` updates to `completed`, `receipt_url` gets populated
8. User sees "View Receipt" link on the order detail page

---

## Testing the callback manually

You can test the callback receiver without the full pipeline:

```bash
curl -X POST http://localhost:8000/webhooks/receipt-callback \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: your-shared-secret-here" \
  -d '{
    "order_reference": "your-order-uuid-here",
    "receipt_id": "some-receipt-uuid",
    "receipt_url": "https://receipts.example.com/r/some-receipt-uuid?t=abc123",
    "status": "completed"
  }'
```
