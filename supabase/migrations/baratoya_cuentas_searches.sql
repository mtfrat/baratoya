-- Cuentas: cupo de búsquedas y búsquedas guardadas.
-- No guarda tarjeta, CVV ni tablas de cobro con datos sensibles.
-- El cupo lo mueve solo el rol de servicio (RPC). El usuario no puede subirse el plan.

alter table public.profiles
  add column if not exists plan text not null default 'free',
  add column if not exists searches_used integer not null default 0,
  add column if not exists paid_at timestamptz,
  add column if not exists mp_payment_id text;

alter table public.profiles
  drop constraint if exists profiles_plan_known;
alter table public.profiles
  add constraint profiles_plan_known check (plan in ('free', 'paid'));

alter table public.profiles
  drop constraint if exists profiles_searches_used_nonnegative;
alter table public.profiles
  add constraint profiles_searches_used_nonnegative check (searches_used >= 0);

comment on column public.profiles.plan is
  'free: hasta 5 búsquedas. paid: búsquedas ilimitadas, marcado solo por el webhook con el rol de servicio. No es un medio de pago.';
comment on column public.profiles.searches_used is
  'Búsquedas ya contadas en el servidor. El browser no lo incrementa.';
comment on column public.profiles.mp_payment_id is
  'Id de pago de Mercado Pago, no un número de tarjeta.';

create table if not exists public.searches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  query text not null,
  created_at timestamptz not null default now(),
  constraint searches_query_not_blank check (length(btrim(query)) > 0),
  constraint searches_query_len check (char_length(query) <= 80)
);

comment on table public.searches is
  'Búsquedas pasadas del usuario. No es un carrito y no compra en el supermercado.';

create index if not exists searches_user_created_idx
  on public.searches (user_id, created_at desc);

alter table public.searches enable row level security;

drop policy if exists searches_select_own on public.searches;
create policy searches_select_own on public.searches
  for select to authenticated
  using (user_id = auth.uid());

revoke insert, update, delete on table public.searches from anon, authenticated;

revoke update on table public.profiles from anon, authenticated;
grant update (display_name) on table public.profiles to authenticated;

create or replace function public.protect_profile_billing()
returns trigger
language plpgsql
as $$
begin
  if current_user in ('postgres', 'supabase_admin', 'service_role') then
    return new;
  end if;
  if coalesce(auth.role(), '') = 'service_role' then
    return new;
  end if;
  new.plan := old.plan;
  new.searches_used := old.searches_used;
  new.paid_at := old.paid_at;
  new.mp_payment_id := old.mp_payment_id;
  return new;
end;
$$;

drop trigger if exists profiles_protect_billing on public.profiles;
create trigger profiles_protect_billing
  before update on public.profiles
  for each row execute function public.protect_profile_billing();

create or replace function public.consume_search(p_user uuid, p_query text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  prof public.profiles%rowtype;
  lim integer := 5;
  q text := left(btrim(coalesce(p_query, '')), 80);
begin
  if p_user is null or q = '' then
    return jsonb_build_object('ok', false, 'reason', 'bad_query');
  end if;
  insert into public.profiles (id) values (p_user)
  on conflict (id) do nothing;
  select * into prof from public.profiles where id = p_user for update;
  if prof.plan = 'paid' then
    insert into public.searches (user_id, query) values (p_user, q);
    return jsonb_build_object(
      'ok', true,
      'plan', 'paid',
      'used', prof.searches_used,
      'remaining', null,
      'limit', lim
    );
  end if;
  if prof.searches_used >= lim then
    return jsonb_build_object(
      'ok', false,
      'reason', 'quota',
      'plan', 'free',
      'used', prof.searches_used,
      'remaining', 0,
      'limit', lim
    );
  end if;
  update public.profiles
    set searches_used = searches_used + 1
    where id = p_user
    returning * into prof;
  insert into public.searches (user_id, query) values (p_user, q);
  return jsonb_build_object(
    'ok', true,
    'plan', 'free',
    'used', prof.searches_used,
    'remaining', lim - prof.searches_used,
    'limit', lim
  );
end;
$$;

revoke all on function public.consume_search(uuid, text) from public;
revoke all on function public.consume_search(uuid, text) from anon, authenticated;
grant execute on function public.consume_search(uuid, text) to service_role;

create or replace function public.mark_profile_paid(p_user uuid, p_payment text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  pay text := left(btrim(coalesce(p_payment, '')), 64);
begin
  if p_user is null or pay = '' then
    return jsonb_build_object('ok', false, 'reason', 'bad_payment');
  end if;
  insert into public.profiles (id) values (p_user)
  on conflict (id) do nothing;
  update public.profiles
    set plan = 'paid',
        paid_at = coalesce(paid_at, now()),
        mp_payment_id = pay
    where id = p_user;
  return jsonb_build_object('ok', true, 'plan', 'paid');
end;
$$;

revoke all on function public.mark_profile_paid(uuid, text) from public;
revoke all on function public.mark_profile_paid(uuid, text) from anon, authenticated;
grant execute on function public.mark_profile_paid(uuid, text) to service_role;
