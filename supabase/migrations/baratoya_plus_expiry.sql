-- Plus pago vence: el cobro es Checkout Pro (pago único), no una suscripción.
-- Cada pago aprobado suma 30 días a profiles.paid_until. Sin paid_until vigente no hay Plus.
-- NO aplicada en prod todavía: aplicar ANTES de mergear el PR (la app lee paid_until).

alter table public.profiles add column if not exists paid_until timestamptz;

-- Pagos ya anotados: idempotencia del webhook por payment_id.
create table if not exists public.mp_payments (
  payment_id text primary key,
  user_id uuid not null references public.profiles (id) on delete cascade,
  days integer not null,
  paid_until timestamptz not null,
  created_at timestamptz not null default now()
);
alter table public.mp_payments enable row level security;
revoke all on table public.mp_payments from public, anon, authenticated;
grant select, insert on table public.mp_payments to service_role;

-- Backfill: pagos previos valen 30 días desde paid_at (en prod hoy hay 0 perfiles pagos).
-- Si ya pasaron, el usuario queda como "Plus vencido" y puede renovar.
update public.profiles
  set paid_until = paid_at + interval '30 days'
  where paid_at is not null and paid_until is null;
insert into public.mp_payments (payment_id, user_id, days, paid_until)
  select mp_payment_id, id, 30, paid_until from public.profiles
  where mp_payment_id is not null and paid_until is not null
  on conflict (payment_id) do nothing;

-- mark_profile_paid: idempotente por pago, suma p_days desde el mayor entre ahora y paid_until
-- (renovar antes de vencer no pierde días).
drop function if exists public.mark_profile_paid(uuid, text);
create or replace function public.mark_profile_paid(p_user uuid, p_payment text, p_days integer default 30)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  pay text := left(btrim(coalesce(p_payment, '')), 64);
  d integer := coalesce(p_days, 30);
  prev timestamptz;
  hasta timestamptz;
  inserted integer;
begin
  if p_user is null or pay = '' or d < 1 or d > 366 then
    return jsonb_build_object('ok', false, 'reason', 'bad_payment');
  end if;
  insert into public.profiles (id) values (p_user) on conflict (id) do nothing;
  select paid_until into prev from public.profiles where id = p_user for update;
  hasta := greatest(coalesce(prev, now()), now()) + make_interval(days => d);
  insert into public.mp_payments (payment_id, user_id, days, paid_until)
    values (pay, p_user, d, hasta)
    on conflict (payment_id) do nothing;
  get diagnostics inserted = row_count;
  if inserted = 0 then
    select paid_until into hasta from public.profiles where id = p_user;
    return jsonb_build_object('ok', true, 'plan', 'paid', 'duplicate', true, 'paid_until', hasta);
  end if;
  update public.profiles
    set plan = 'paid',
        paid_at = coalesce(paid_at, now()),
        paid_until = hasta,
        mp_payment_id = pay
    where id = p_user;
  return jsonb_build_object('ok', true, 'plan', 'paid', 'duplicate', false, 'paid_until', hasta);
end;
$$;
revoke all on function public.mark_profile_paid(uuid, text, integer) from public, anon, authenticated;
grant execute on function public.mark_profile_paid(uuid, text, integer) to service_role;

-- consume_search: "paid" solo si paid_until está vigente.
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
  if prof.role = 'admin' then
    insert into public.searches (user_id, query) values (p_user, q);
    return jsonb_build_object('ok', true, 'plan', prof.plan, 'role', 'admin',
      'used', prof.searches_used, 'remaining', null, 'limit', null);
  end if;
  if prof.plan = 'paid' and prof.paid_until is not null and prof.paid_until > now() then
    insert into public.searches (user_id, query) values (p_user, q);
    return jsonb_build_object('ok', true, 'plan', 'paid', 'role', 'user',
      'used', prof.searches_used, 'remaining', null, 'limit', lim);
  end if;
  if prof.searches_used >= lim then
    return jsonb_build_object('ok', false, 'reason', 'quota', 'plan', 'free', 'role', 'user',
      'used', prof.searches_used, 'remaining', 0, 'limit', lim);
  end if;
  update public.profiles
    set searches_used = searches_used + 1
    where id = p_user
    returning * into prof;
  insert into public.searches (user_id, query) values (p_user, q);
  return jsonb_build_object('ok', true, 'plan', 'free', 'role', 'user',
    'used', prof.searches_used, 'remaining', lim - prof.searches_used, 'limit', lim);
end;
$$;
revoke all on function public.consume_search(uuid, text) from public, anon, authenticated;
grant execute on function public.consume_search(uuid, text) to service_role;

-- Trigger: paid_until también es campo protegido (solo servidor / funciones definer).
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
  if new.trial_ends_at is distinct from old.trial_ends_at
     or new.plan is distinct from old.plan
     or new.is_test is distinct from old.is_test
     or new.role is distinct from old.role
     or new.paid_at is distinct from old.paid_at
     or new.paid_until is distinct from old.paid_until
     or new.mp_payment_id is distinct from old.mp_payment_id
     or new.searches_used is distinct from old.searches_used
     or new.id is distinct from old.id
     or new.created_at is distinct from old.created_at then
    raise exception 'profiles: campo protegido, solo el servidor puede cambiarlo'
      using errcode = '42501';
  end if;
  if new.prefs is not null and jsonb_typeof(new.prefs) = 'object' and new.prefs ? 'trial_ends_at' then
    new.prefs := new.prefs - 'trial_ends_at';
  end if;
  return new;
end;
$$;
