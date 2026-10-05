-- Admin role. The search quota stays at 5 for a normal account. Admin is not capped.
-- No payments table and no invented charges.

alter table public.profiles
  add column if not exists role text not null default 'user';

alter table public.profiles
  drop constraint if exists profiles_role_known;
alter table public.profiles
  add constraint profiles_role_known check (role in ('user', 'admin'));

comment on column public.profiles.role is
  'user: cupo de 5 búsquedas. admin: sin tope. El usuario no puede cambiar este valor.';

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
  new.role := old.role;
  return new;
end;
$$;

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
    return jsonb_build_object(
      'ok', true,
      'plan', prof.plan,
      'role', 'admin',
      'used', prof.searches_used,
      'remaining', null,
      'limit', null
    );
  end if;
  if prof.plan = 'paid' then
    insert into public.searches (user_id, query) values (p_user, q);
    return jsonb_build_object(
      'ok', true,
      'plan', 'paid',
      'role', 'user',
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
      'role', 'user',
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
    'role', 'user',
    'used', prof.searches_used,
    'remaining', lim - prof.searches_used,
    'limit', lim
  );
end;
$$;

revoke all on function public.consume_search(uuid, text) from public;
revoke all on function public.consume_search(uuid, text) from anon, authenticated;
grant execute on function public.consume_search(uuid, text) to service_role;

create or replace function public.admin_stats()
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  n_users integer;
  n_searches integer;
  n_paid integer;
  n_payments integer;
  has_payments boolean;
begin
  select count(*) into n_users from auth.users where deleted_at is null;
  select count(*) into n_searches from public.searches;
  select count(*) into n_paid from public.profiles where plan = 'paid';
  select exists (
    select 1 from information_schema.tables
    where table_schema = 'public' and table_name = 'payments'
  ) into has_payments;
  if has_payments then
    execute 'select count(*) from public.payments' into n_payments;
  else
    n_payments := null;
  end if;
  return jsonb_build_object(
    'usuarios', n_users,
    'busquedas', n_searches,
    'perfiles_pagos', n_paid,
    'pagos', n_payments,
    'ingresos_centavos', 0
  );
end;
$$;

revoke all on function public.admin_stats() from public;
revoke all on function public.admin_stats() from anon, authenticated;
grant execute on function public.admin_stats() to service_role;
