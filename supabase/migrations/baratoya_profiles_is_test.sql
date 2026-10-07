-- Marca cuentas de prueba (smoke/QA) para excluirlas de las métricas de usuarios reales.
-- No borra nada. Para métricas: WHERE NOT p.is_test (y role <> 'admin' si se excluye la cuenta de la casa).

alter table public.profiles
  add column if not exists is_test boolean not null default false;

comment on column public.profiles.is_test is
  'true = cuenta de prueba (smoke/QA). Excluir de métricas de usuarios reales. Solo lo cambia service_role/postgres.';

-- El usuario no puede marcarse/desmarcarse como test con su JWT.
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
  new.is_test := old.is_test;
  return new;
end;
$$;

-- Patrones de cuentas de prueba: smoke*, *@mailinator.com, alias +qa en Gmail.
update public.profiles p
set is_test = true
from auth.users u
where u.id = p.id
  and p.is_test = false
  and (
    u.email ilike 'smoke%'
    or u.email ilike '%@mailinator.com'
    or u.email ~* '\+qa[^@]*@'
  );

update auth.users u
set raw_app_meta_data = coalesce(u.raw_app_meta_data, '{}'::jsonb) || '{"is_test": true}'::jsonb
from public.profiles p
where p.id = u.id
  and p.is_test
  and coalesce(u.raw_app_meta_data ->> 'is_test', '') <> 'true';
