# BaratoYa P0 — Funnel trial → Plus

**Status:** CEO approved (Money brief). Implement + ship.
**Repo:** mtfrat/baratoya · prod https://www.baratoya.app
**Branch:** `feat/trial-funnel-p0` from `origin/master` (7ded95b+)
**Worktree (Windows):** `C:\Users\martin\Documents\worktrees\baratoya-trial`
**Do not ping Martin** — report to CEO via Product.

## Problem
2 signups, 0 with `trial_ends_at`, 0 paid. Product promises 7d Plus gratis on account create; backend does not reliably persist `trial_ends_at`.

### Root cause (confirmed)
- Signup is client → Supabase Auth `/auth/v1/signup` (no backend call).
- `cuentas.activar_trial(user_id)` PATCHes `profiles.trial_ends_at`.
- `leer_cuenta` if missing `trial_ends_at` and no `paid_at`: computes now+7d **in memory** and `asyncio.create_task(activar_trial(...))` with bare `except: pass` — fire-and-forget, unreliable.

## Scope (same ship)

### A) Backend — persist trial
1. **Await** `activar_trial` on first `/api/cuenta` (`leer_cuenta`) instead of `create_task`.
2. Make `activar_trial` check PATCH status; return ISO on success, `""` on failure (no silent fake success for callers that need persistence).
3. After successful signup, client calls `GET /api/cuenta` (already does via session) **and** optionally `POST /api/cuenta/activar-trial` right after signup for belt-and-suspenders.
4. Plan effective = Plus while trial active (already true in `calcular_plan_efectivo`).
5. Tests: unit/integration proving await path persists / returns trial_ends_at; no create_task for new accounts.
6. **Backfill** (CEO OK): SQL for existing users with null `trial_ends_at` and null `paid_at` → set `now()+7 days` UTC. Document + apply via Supabase if safe.

### B) Copy Exp1+2 — trial-first (home + /planes)
- Hero: “Probar 7d Plus gratis”
- Primary CTA: “Empezar 7d gratis” → signup modal
- Secondary: “Suscribirme · $1.990” (or plan_label)
- Gratis card: create account = 7d Plus
- FAQ: cobro día 8 **solo si se suscriben**; trial does **NOT** auto-charge (after trial → free 5 searches; Plus optional via MP)
- Align modal: “7 días Plus gratis, sin tarjeta”
- No invented savings amounts

### C) GA4 (G-5X047YX59B / env)
Minimum events:
- `sign_up`
- `trial_start` (or `begin_trial`) when trial is confirmed active after signup/`/api/cuenta`
- `begin_checkout` when starting MP checkout
- `purchase` / `subscribe` with `value: 1990`, `currency: ARS`, `transaction_id` = MP preference/payment id
Optional if easy: `view_plans`, `cta_click`

## Out of scope
Exp3 onboarding checklist, ML search, affiliates.

## Ship
1. Implement on Windows worktree `feat/trial-funnel-p0`.
2. Run tests. Commit. Push `-u origin` (no force). Open PR → master.
3. Prefer Antigravity/OpenCode if available; else implement carefully via Shell.
4. Do not reset `--hard` the main `Documents\baratoya` tree (has untracked BRIEFs). Never stage unrelated BRIEF files.

## Success criteria
- [ ] tests prove trial persist path
- [ ] `leer_cuenta` awaits `activar_trial` (no fire-and-forget only)
- [ ] home + /planes trial-first copy
- [ ] GA4 events at right moments
- [ ] report: branch, tip SHA, PR URL, pending (backfill applied?, migration in prod)

## Product truth (billing)
Trial = 7 days Plus, no card, no auto-charge. After trial → free plan (5 searches). Plus = optional Mercado Pago subscription ($1.990/mes). Charging starts only when user chooses Plus.
