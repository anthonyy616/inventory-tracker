-- Add receipt_error column to orders table
-- This column stores error messages from receipt generation failures

ALTER TABLE orders ADD COLUMN IF NOT EXISTS receipt_error TEXT;

-- Index for receipt status queries
CREATE INDEX IF NOT EXISTS idx_orders_receipt_status ON orders(receipt_status);
