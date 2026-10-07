-- Seguridad: el usuario podía extender su propio trial (PATCH profiles.trial_ends_at con su JWT).
-- 1) RPC activar_trial(): única vía del usuario para iniciar el trial (idempotente, auth.uid()).
-- 2) authenticated solo puede UPDATE prefs y display_name; el trigger rechaza cambios a campos protegidos.
-- 3) admin_stats mide solo usuarios reales (sin is_test ni admin) y agrega totales crudos.

create or replace function public.activar_trial()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  uid uuid := auth.uid();
  prof public.profiles%rowtype;
  activado boolean := false;
begin
  if uid is null then
    return jsonb_build_object('ok', false, 'reason', 'auth');
  end if;
  select * into prof from public.profiles where id = uid for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'no_profile');
  end if;
  -- Misma regla que la app: sin trial previo, sin pago real, no admin.
  if prof.trial_ends_at is null
     and prof.paid_at is null
     and coalesce(prof.plan, 'free') <> 'paid'
     and coalesce(prof.role, 'user') <> 'admin' then
    update public.profiles
      set trial_ends_at = now() + interval '7 days'
      where id = uid
      returning * into prof;
    activado := true;
  end if;
  return jsonb_build_object(
    'ok', true,
    'activado', activado,
    'trial_ends_at', prof.trial_ends_at,
    'plan', prof.plan,
    'paid_at', prof.paid_at,
    'role', prof.role
  );
end;
$$;

revoke all on function public.activar_trial() from public, anon, service_role;
grant execute on function public.activar_trial() to authenticated;

-- Grants por columna: el usuario solo edita sus preferencias y su nombre.
revoke update on table public.profiles from anon, authenticated;
grant update (prefs, display_name) on table public.profiles to authenticated;

-- Segunda capa: aunque alguien tenga UPDATE, un rol no privilegiado no cambia campos protegidos.
-- postgres/supabase_admin (RPCs SECURITY DEFINER: activar_trial, mark_profile_paid,
-- consume_search) y service_role (webhook Mercado Pago, servidor) siguen pudiendo.
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
     or new.mp_payment_id is distinct from old.mp_payment_id
     or new.searches_used is distinct from old.searches_used
     or new.id is distinct from old.id
     or new.created_at is distinct from old.created_at then
    raise exception 'profiles: campo protegido, solo el servidor puede cambiarlo'
      using errcode = '42501';
  end if;
  -- Un trial guardado en prefs no vale: se descarta.
  if new.prefs is not null and jsonb_typeof(new.prefs) = 'object' and new.prefs ? 'trial_ends_at' then
    new.prefs := new.prefs - 'trial_ends_at';
  end if;
  return new;
end;
$$;

-- Métricas: mismas claves que antes, ahora solo usuarios reales; *_total = crudo.
create or replace function public.admin_stats()
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  n_users integer;
  n_users_total integer;
  n_test integer;
  n_admin integer;
  n_searches integer;
  n_searches_total integer;
  n_paid integer;
  n_paid_total integer;
  n_payments integer;
  has_payments boolean;
begin
  select count(*) into n_users_total from auth.users where deleted_at is null;
  select count(*) into n_users
    from auth.users u left join public.profiles p on p.id = u.id
    where u.deleted_at is null
      and not coalesce(p.is_test, false)
      and coalesce(p.role, 'user') <> 'admin';
  select count(*) into n_test from public.profiles where is_test;
  select count(*) into n_admin from public.profiles where role = 'admin';
  select count(*) into n_searches_total from public.searches;
  select count(*) into n_searches
    from public.searches s join public.profiles p on p.id = s.user_id
    where not p.is_test and coalesce(p.role, 'user') <> 'admin';
  select count(*) into n_paid_total from public.profiles where plan = 'paid';
  select count(*) into n_paid from public.profiles
    where plan = 'paid' and not is_test and coalesce(role, 'user') <> 'admin';
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
    'ingresos_centavos', 0,
    'usuarios_total', n_users_total,
    'usuarios_test', n_test,
    'usuarios_admin', n_admin,
    'busquedas_total', n_searches_total,
    'perfiles_pagos_total', n_paid_total
  );
end;
$$;

revoke all on function public.admin_stats() from public, anon, authenticated;
grant execute on function public.admin_stats() to service_role;
