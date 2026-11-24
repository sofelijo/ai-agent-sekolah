-- Run against the original DB after the dashboard schema exists.
CREATE UNIQUE INDEX IF NOT EXISTS idx_bullying_public_submission
ON public.bullying_reports ((metadata->>'submission_id'))
WHERE metadata->>'source'='public_landingpage';
CREATE INDEX IF NOT EXISTS idx_bullying_public_peer
ON public.bullying_reports ((metadata->>'ip_hash'),created_at)
WHERE metadata->>'source'='public_landingpage';
