-- BaratoYa: búsqueda anónima (sin cuenta) con tope por IP y cookie firmada.
-- NO aplicar a prod hasta el OK de Martin. Idempotente.
--
-- Desde el 30-10 Supabase exige GRANT explícito en tablas nuevas de public.
-- Esta tabla y su RPC son solo del rol de servicio: anon/authenticated no
-- leen, no escriben y no ejecutan. RLS prendido y sin políticas.
--
-- La IP nunca se guarda en claro: el server guarda HMAC-SHA256(ip) truncado.

create table if not exists public.anon_search_events (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  ip_hash text not null check (char_length(ip_hash) between 8 and 64),
  anon_id text check (anon_id is null or char_length(anon_id) <= 64),
  query text not null check (char_length(query) between 1 and 80)
);

create index if not exists anon_search_events_ip_created
  on public.anon_search_events (ip_hash, created_at desc);
create index if not exists anon_search_events_anon_created
  on public.anon_search_events (anon_id, created_at desc)
  where anon_id is not null;
create index if not exists anon_search_events_created
  on public.anon_search_events (created_at desc);

alter table public.anon_search_events enable row level security;

revoke all on table public.anon_search_events from public, anon, authenticated;
grant select, insert, delete on table public.anon_search_events to service_role;
grant usage, select on sequence public.anon_search_events_id_seq to service_role;
revoke all on sequence public.anon_search_events_id_seq from public, anon, authenticated;

-- Cuenta y registra en una sola llamada (lock por ip_hash para que dos
-- requests paralelas no pasen las dos el tope). Solo registra si pasa.
create or replace function public.anon_search_hit(
  p_ip_hash text,
  p_anon_id text,
  p_query text,
  p_hour_limit integer default 10,
  p_day_limit integer default 30
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  q text := left(btrim(coalesce(p_query, '')), 80);
  ip_hour integer;
  ip_day integer;
  an_hour integer := 0;
  an_day integer := 0;
  used_hour integer;
  used_day integer;
begin
  if p_ip_hash is null or char_length(p_ip_hash) < 8 or char_length(p_ip_hash) > 64 then
    return jsonb_build_object('ok', false, 'reason', 'bad_ip');
  end if;
  if q = '' then
    return jsonb_build_object('ok', false, 'reason', 'bad_query');
  end if;
  if p_anon_id is not null and char_length(p_anon_id) > 64 then
    p_anon_id := null;
  end if;

  perform pg_advisory_xact_lock(hashtext('anon_search:' || p_ip_hash));

  select count(*) filter (where created_at > now() - interval '1 hour'),
         count(*)
    into ip_hour, ip_day
    from public.anon_search_events
   where ip_hash = p_ip_hash
     and created_at > now() - interval '24 hours';

  if p_anon_id is not null then
    select count(*) filter (where created_at > now() - interval '1 hour'),
           count(*)
      into an_hour, an_day
      from public.anon_search_events
     where anon_id = p_anon_id
       and created_at > now() - interval '24 hours';
  end if;

  used_hour := greatest(ip_hour, an_hour);
  used_day := greatest(ip_day, an_day);

  if used_day >= p_day_limit then
    return jsonb_build_object('ok', false, 'reason', 'rate_day',
      'hour', used_hour, 'day', used_day,
      'hour_limit', p_hour_limit, 'day_limit', p_day_limit);
  end if;
  if used_hour >= p_hour_limit then
    return jsonb_build_object('ok', false, 'reason', 'rate_hour',
      'hour', used_hour, 'day', used_day,
      'hour_limit', p_hour_limit, 'day_limit', p_day_limit);
  end if;

  insert into public.anon_search_events (ip_hash, anon_id, query)
  values (p_ip_hash, p_anon_id, q);

  -- Limpieza perezosa: guardar 90 días alcanza para métricas.
  if random() < 0.01 then
    delete from public.anon_search_events where created_at < now() - interval '90 days';
  end if;

  return jsonb_build_object('ok', true,
    'hour', used_hour + 1, 'day', used_day + 1,
    'hour_limit', p_hour_limit, 'day_limit', p_day_limit);
end;
$$;

revoke all on function public.anon_search_hit(text, text, text, integer, integer) from public, anon, authenticated;
grant execute on function public.anon_search_hit(text, text, text, integer, integer) to service_role;

-- admin_stats: mismo cuerpo que antes (excluye is_test y admin en búsquedas
-- con cuenta) + volumen anónimo. Las anónimas no tienen usuario, así que no
-- hay is_test/admin que excluir: un admin que busca sin sesión cuenta como anónimo.
create or replace function public.admin_stats()
 returns jsonb
 language plpgsql
 security definer
 set search_path to 'public', 'auth'
as $function$
declare
  n_users integer;
  n_users_total integer;
  n_test integer;
  n_admin integer;
  n_searches integer;
  n_searches_total integer;
  n_anon integer;
  n_anon_24h integer;
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
  select count(*), count(*) filter (where created_at > now() - interval '24 hours')
    into n_anon, n_anon_24h
    from public.anon_search_events;
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
    'busquedas_sin_cuenta', n_anon,
    'busquedas_sin_cuenta_24h', n_anon_24h,
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
$function$;

revoke all on function public.admin_stats() from public, anon, authenticated;
grant execute on function public.admin_stats() to service_role;
