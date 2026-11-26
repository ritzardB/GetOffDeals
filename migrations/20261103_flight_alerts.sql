BEGIN;

CREATE TABLE IF NOT EXISTS public.flight_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID NOT NULL
        REFERENCES public.users(id)
        ON DELETE CASCADE,

    origin VARCHAR(3) NOT NULL,
    destination VARCHAR(3) NOT NULL,

    departure_date DATE NOT NULL,
    return_date DATE,

    adults SMALLINT NOT NULL DEFAULT 1,
    cabin_class TEXT NOT NULL DEFAULT 'ECONOMY',

    target_price NUMERIC(14, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'AED',

    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_checked_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT flight_alerts_different_airports
        CHECK (origin <> destination),

    CONSTRAINT flight_alerts_valid_adults
        CHECK (adults BETWEEN 1 AND 9),

    CONSTRAINT flight_alerts_valid_cabin
        CHECK (
            cabin_class IN (
                'ECONOMY',
                'PREMIUM_ECONOMY',
                'BUSINESS',
                'FIRST'
            )
        ),

    CONSTRAINT flight_alerts_valid_currency
        CHECK (currency IN ('AED', 'USD', 'PHP')),

    CONSTRAINT flight_alerts_positive_target_price
        CHECK (target_price > 0),

    CONSTRAINT flight_alerts_valid_return_date
        CHECK (
            return_date IS NULL
            OR return_date > departure_date
        )
);

CREATE INDEX IF NOT EXISTS idx_flight_alerts_user_created
    ON public.flight_alerts(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_flight_alerts_active
    ON public.flight_alerts(is_active)
    WHERE is_active = TRUE;

COMMIT;
