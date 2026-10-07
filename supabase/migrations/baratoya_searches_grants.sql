-- Búsquedas de usuarios en trial no se guardaban.
-- Causa: public.searches no tenía GRANT SELECT/INSERT para service_role ni SELECT
-- para authenticated (solo TRUNCATE/REFERENCES/TRIGGER). PostgREST devolvía 42501
-- y cuentas.consumir() ignoraba la respuesta. El RPC consume_search (SECURITY DEFINER)
-- sí insertaba, por eso solo había búsquedas del admin/free.
-- El usuario sigue sin poder insertar/editar/borrar: solo lee sus filas (RLS).

grant select, insert on table public.searches to service_role;
grant select on table public.searches to authenticated;
revoke insert, update, delete on table public.searches from anon, authenticated;
