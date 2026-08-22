-- Drop and recreate the create_order RPC function
-- This runs entirely within a single Postgres transaction

-- Drop the old 4-param version AND any 5-param version that may exist
DROP FUNCTION IF EXISTS create_order(uuid, text, jsonb, text);
DROP FUNCTION IF EXISTS create_order(uuid, text, jsonb, text, text);

CREATE OR REPLACE FUNCTION create_order(
    p_company_id UUID,
    p_customer_name TEXT,
    p_items JSONB,
    p_customer_email TEXT DEFAULT NULL,
    p_receipt_client_id TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_order_id UUID;
    v_order_number TEXT;
    v_subtotal NUMERIC(12,2) := 0;
    v_tax NUMERIC(12,2) := 0;
    v_total NUMERIC(12,2) := 0;
    v_item JSONB;
    v_product RECORD;
    v_new_stock INTEGER;
    v_line_total NUMERIC(12,2);
    v_line_items JSONB := '[]'::JSONB;
BEGIN
    -- Generate order ID and order number
    v_order_id := gen_random_uuid();
    v_order_number := 'ORD-' || TO_CHAR(NOW(), 'YYYYMMDD') || '-' || LEFT(v_order_id::TEXT, 8);

    -- Step 1: Validate stock and compute totals
    FOR v_item IN SELECT * FROM jsonb_array_elements(p_items)
    LOOP
        -- Attempt to decrement stock atomically
        UPDATE products
        SET quantity_in_stock = quantity_in_stock - (v_item->>'quantity')::INTEGER,
            updated_at = NOW()
        WHERE id = (v_item->>'product_id')::UUID
          AND quantity_in_stock >= (v_item->>'quantity')::INTEGER
        RETURNING quantity_in_stock INTO v_new_stock;

        IF v_new_stock IS NULL THEN
            SELECT name INTO v_product FROM products WHERE id = (v_item->>'product_id')::UUID;
            RAISE EXCEPTION 'Insufficient stock for product: %', COALESCE(v_product.name, 'Unknown');
        END IF;

        -- Get product details for snapshotting
        SELECT name, unit_price INTO v_product
        FROM products WHERE id = (v_item->>'product_id')::UUID;

        v_line_total := v_product.unit_price * (v_item->>'quantity')::INTEGER;
        v_subtotal := v_subtotal + v_line_total;

        -- Build line item for receipt payload
        v_line_items := v_line_items || jsonb_build_object(
            'description', v_product.name,
            'quantity', (v_item->>'quantity')::INTEGER,
            'unit_price', v_product.unit_price,
            'line_total', v_line_total
        );
    END LOOP;

    -- Compute tax (placeholder 0% for now)
    v_tax := 0;
    v_total := v_subtotal + v_tax;

    -- Step 2: Insert order header
    INSERT INTO orders (id, company_id, order_number, customer_name, status, subtotal, tax, total, receipt_status)
    VALUES (v_order_id, p_company_id, v_order_number, p_customer_name, 'completed', v_subtotal, v_tax, v_total, 'pending');

    -- Step 3: Insert order items and inventory transactions
    FOR v_item IN SELECT * FROM jsonb_array_elements(p_items)
    LOOP
        SELECT name, unit_price INTO v_product
        FROM products WHERE id = (v_item->>'product_id')::UUID;

        v_line_total := v_product.unit_price * (v_item->>'quantity')::INTEGER;

        INSERT INTO order_items (order_id, product_id, product_name_snapshot, unit_price_snapshot, quantity, line_total)
        VALUES (v_order_id, (v_item->>'product_id')::UUID, v_product.name, v_product.unit_price, (v_item->>'quantity')::INTEGER, v_line_total);

        -- Get resulting stock for transaction log
        SELECT quantity_in_stock INTO v_new_stock
        FROM products WHERE id = (v_item->>'product_id')::UUID;

        INSERT INTO inventory_transactions (product_id, order_id, change_type, quantity_change, resulting_quantity)
        VALUES ((v_item->>'product_id')::UUID, v_order_id, 'sale', -(v_item->>'quantity')::INTEGER, v_new_stock);
    END LOOP;

    -- Step 4: Insert outbox row for receipt generation
    IF p_receipt_client_id IS NOT NULL AND p_receipt_client_id != '' THEN
        INSERT INTO receipt_requests (order_id, client_id, payload, status)
        VALUES (
            v_order_id,
            p_receipt_client_id,
            jsonb_build_object(
                'client_id', p_receipt_client_id,
                'order_reference', v_order_id::TEXT,
                'line_items', v_line_items,
                'subtotal', v_subtotal,
                'tax', v_tax,
                'total', v_total,
                'currency', 'NGN',
                'customer_email', p_customer_email
            ),
            'pending'
        );
    END IF;

    -- Return success
    RETURN jsonb_build_object(
        'success', true,
        'order_id', v_order_id,
        'order_number', v_order_number,
        'total', v_total
    );
END;
$$;
