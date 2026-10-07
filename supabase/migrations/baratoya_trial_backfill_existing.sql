-- Backfill trial for existing free users without trial_ends_at (CEO OK 2026-10-07).
-- Safe: only rows with null trial_ends_at AND null paid_at AND role != admin.
-- Sets trial_ends_at = now() + 7 days (timestamptz / UTC store).

update public.profiles
set trial_ends_at = now() + interval '7 days'
where trial_ends_at is null
  and paid_at is null
  and coalesce(role, 'user') <> 'admin';
