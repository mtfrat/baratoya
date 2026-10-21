-- Capturas de /precios compartidas entre instancias de Vercel.
-- Antes cada instancia guardaba sus lecturas en su /tmp: tras cada deploy (o una instancia
-- nueva) las fichas y el sitemap volvían a la foto del repo (10/10). Una fila por producto,
-- con la última captura leída del catálogo público (nunca escrita a mano).
-- Solo el servidor (service_role) lee y escribe. RLS activo sin políticas: anon y
-- authenticated no ven nada.

create table if not exists public.precios_publicos (
  slug text primary key,
  capturado timestamptz not null,
  captura jsonb not null,
  updated_at timestamptz not null default now()
);

alter table public.precios_publicos enable row level security;

revoke all on table public.precios_publicos from anon, authenticated;
grant select, insert, update on table public.precios_publicos to service_role;

create or replace function public.precios_publicos_touch()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  -- Una captura más vieja nunca pisa una más nueva (dos instancias leyendo a la vez).
  if tg_op = 'UPDATE' and new.capturado < old.capturado then
    return old;
  end if;
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists precios_publicos_touch on public.precios_publicos;
create trigger precios_publicos_touch
before insert or update on public.precios_publicos
for each row execute function public.precios_publicos_touch();
