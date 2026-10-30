ALTER TABLE public.resend_sync_outbox
    DROP CONSTRAINT IF EXISTS resend_sync_outbox_status_check;

ALTER TABLE public.resend_sync_outbox
    ADD CONSTRAINT resend_sync_outbox_status_check
    CHECK (status IN ('pending', 'processing', 'done', 'failed'));
