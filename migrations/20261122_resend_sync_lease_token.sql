-- Add ownership tracking for Resend outbox processing leases.

ALTER TABLE public.resend_sync_outbox
ADD COLUMN IF NOT EXISTS lease_token TEXT;
