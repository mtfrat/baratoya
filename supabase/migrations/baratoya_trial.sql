-- Trial de 7 días BaratoYa Plus (freemium)
-- Permite búsquedas ilimitadas y alertas durante 7 días corridos desde el alta.

alter table public.profiles
  add column if not exists trial_ends_at timestamptz;

comment on column public.profiles.trial_ends_at is
  'Fecha y hora límite del trial de 7 días. Si now() < trial_ends_at, el plan efectivo es Plus.';
