-- Preferencias de usuario en profiles: ver precio con promo, bancos y supermercados.
-- No guarda tarjeta, CVV ni datos sensibles.

alter table public.profiles
  add column if not exists prefs jsonb not null default '{"show_promo_price": true, "banks": [], "supermarkets": []}'::jsonb;

comment on column public.profiles.prefs is
  'Preferencias del usuario: show_promo_price (bool), banks (array de brand_ids), supermarkets (array de chain_ids).';

-- Permitir que el usuario autenticado actualice sus preferencias junto a display_name
grant update (prefs, display_name) on table public.profiles to authenticated;
