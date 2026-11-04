#!/usr/bin/env python3
"""Arma las promos bancarias de la semana (lunes a domingo) y, opcionalmente, abre el PR. NUNCA mergea.

Uso típico (lunes):   python3 scripts/promos_semana.py --pr
Ensayo sin tocar nada: python3 scripts/promos_semana.py --dry-run

Sólo usa páginas y endpoints públicos (sin login, sin cookies, sin tokens). No toca Supabase.
Ver scripts/promos/README.md.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from scripts.promos import build, fetch, validate  # noqa: E402
from scripts.promos.common import CADENAS, lunes_de  # noqa: E402

DATA = Path("data/promos-semana.json")
STATE = Path("scripts/promos/state")
EXIT_OK, EXIT_PENDIENTES, EXIT_ALARMAS, EXIT_TESTS, EXIT_ENTORNO = 0, 2, 3, 4, 5


def log(msg: str) -> None:
    print(msg, flush=True)


def serializar(rows: list[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=1)  # mismo formato que el archivo histórico (sin \n final)


def sh(cmd: list[str], cwd: Path, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if check and r.returncode:
        raise SystemExit(f"falló `{' '.join(cmd)}` en {cwd}:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return r


def escribir_state(raiz: Path, new_state: dict) -> None:
    d = raiz / STATE
    d.mkdir(parents=True, exist_ok=True)
    for nombre, v in new_state.items():
        (d / f"{nombre}.json").write_text(json.dumps(v, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def correr_tests(raiz: Path) -> bool:
    ok = True
    for etiqueta, env in (("suite (reloj y datos fijos)", {}), ("BARATOYA_TESTS_REALES=1 (datos reales, reloj real)", {"BARATOYA_TESTS_REALES": "1"})):
        log(f"[tests] {etiqueta}")
        r = sh([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"], raiz, check=False, env=env)
        ultima = (r.stdout.strip().splitlines() or ["(sin salida)"])[-1]
        log(f"        -> {ultima}")
        if r.returncode:
            ok = False
            log(r.stdout[-3000:])
    return ok


def cuerpo_pr(w0: date, w1: date, ctx, tabla: list[str], alarmas: list[str], cambios: str, tests: str) -> str:
    return "\n".join([
        f"## Promos bancarias semana {w0} → {w1}", "",
        "Generado por `scripts/promos_semana.py` (fuentes públicas, sin login; nada escrito en Supabase).", "",
        "### Resumen por cadena", "```", *tabla, "```", "",
        f"### Cambios vs. la carga anterior\n{cambios}", "",
        "### Alarmas", *(["- " + a for a in alarmas] or ["- ninguna"]), "",
        "### Pendientes / avisos", *(["- " + f"{u['chain']}: {u['reason']}" for u in ctx.unresolved] or ["- ninguno"]), "",
        f"### Tests\n{tests}", "",
        "### Regla BaratoYa", "Las promos bancarias van aparte del precio; el pipeline sólo carga datos (`data/promos-semana.json`) y `test_promos_no_restan.py` "
        "protege que la app no las reste fuera de los casos documentados.", "",
        "**No mergear sin OK explícito de Martin.** Revisar el diff de `data/promos-semana.json` y `scripts/promos/state/`.",
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--semana", help="lunes de la semana a armar (YYYY-MM-DD); por defecto, la semana de hoy (o la próxima si hoy es domingo)")
    ap.add_argument("--dry-run", action="store_true", help="arma y valida todo en .promos-work/ y corre los tests sobre una copia; no toca el repo, ni git, ni GitHub")
    ap.add_argument("--pr", action="store_true", help="rama + commit + push + gh pr create (nunca merge)")
    ap.add_argument("--base", default="master", help="rama base del PR (default: master)")
    ap.add_argument("--no-fetch", action="store_true", help="no descarga; usa --raw-dir")
    ap.add_argument("--raw-dir", type=Path, help="directorio con las fuentes ya descargadas")
    ap.add_argument("--overrides", type=Path, help="JSON {clave: spec} con lo resuelto a mano para los pendientes (ver pendientes.json)")
    ap.add_argument("--aprobar-paginas", default="", help="cadenas (coma) cuya página cambió y ya revisaste: se mantienen sus filas")
    ap.add_argument("--allow-unresolved", action="store_true", help="descarta los pendientes y sigue (quedan listados en el PR)")
    ap.add_argument("--allow-alarms", action="store_true", help="sigue aunque haya alarmas (cadena vacía o caída fuerte)")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--gh-user", default="mtfrat", help="usuario de gh esperado para --pr")
    a = ap.parse_args()

    hoy = date.today()
    w0 = lunes_de(date.fromisoformat(a.semana)) if a.semana else lunes_de(hoy + timedelta(days=1 if hoy.weekday() == 6 else 0))
    w1 = w0 + timedelta(days=6)
    log(f"=== Promos semana {w0} (lunes) → {w1} (domingo) | modo: {'dry-run' if a.dry_run else 'pr' if a.pr else 'local'} ===")

    trabajo = RAIZ / ".promos-work" / w0.isoformat()
    trabajo.mkdir(parents=True, exist_ok=True)
    raw = a.raw_dir or trabajo / "raw"
    if a.no_fetch:
        if not a.raw_dir:
            log("--no-fetch requiere --raw-dir")
            return EXIT_ENTORNO
    else:
        raw.mkdir(parents=True, exist_ok=True)
        log(f"[fetch] descargando fuentes públicas a {raw}")
        try:
            fetch.fetch_all(raw, log)
        except fetch.FetchError as e:
            log(f"ERROR de fuente: {e}\nNo se arma la semana con datos incompletos.")
            return EXIT_ENTORNO

    if a.pr and not a.dry_run:
        if not shutil.which("gh"):
            log("ERROR: falta gh en el PATH")
            return EXIT_ENTORNO
        quien = sh(["gh", "api", "user", "-q", ".login"], RAIZ, check=False).stdout.strip()
        if quien != a.gh_user:
            log(f"ERROR: gh está autenticado como {quien or '(nadie)'}, se esperaba {a.gh_user}. `gh auth login` / `gh auth switch`.")
            return EXIT_ENTORNO

    baseline = json.loads((RAIZ / DATA).read_text(encoding="utf-8"))
    overrides = json.loads(a.overrides.read_text(encoding="utf-8")) if a.overrides else {}
    ctx = build.armar(w0, raw, RAIZ / STATE, overrides, baseline, {x.strip() for x in a.aprobar_paginas.split(",") if x.strip()})

    code = EXIT_OK
    if ctx.unresolved:
        pf = trabajo / "pendientes.json"
        pf.write_text(json.dumps(ctx.unresolved, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"\nPENDIENTES ({len(ctx.unresolved)}): hay que leer la fuente y resolverlos a mano. Detalle y plantillas en {pf.relative_to(RAIZ)}")
        for u in ctx.unresolved:
            log(f"  - [{u['chain']}] {u['key']}: {u['reason']}")
        if not a.allow_unresolved:
            log("Se frena: no se inventan datos. Completá --overrides (o usá --allow-unresolved para descartarlos).")
            code = EXIT_PENDIENTES
        else:
            log("--allow-unresolved: se siguen sin esas filas (quedan listadas en el PR).")

    meta = STATE / "meta.json"
    w_prev = date.fromisoformat(json.loads((RAIZ / meta).read_text(encoding="utf-8"))["semana"]) if (RAIZ / meta).exists() else None
    ctx.new_state["meta"] = {"semana": w0.isoformat()}
    al, tabla = validate.alarmas(ctx.rows, baseline, w0, w_prev)
    log("\nResumen por cadena:\n  " + "\n  ".join(tabla))
    if al:
        log("\nALARMAS:\n  " + "\n  ".join("!! " + x for x in al))
        if not a.allow_alarms:
            log("Se frena: revisar si la fuente cayó o cambió. (--allow-alarms para seguir sabiendo lo que pasa.)")
            code = code or EXIT_ALARMAS
    if code:
        return code

    nuevo = serializar(ctx.rows)
    viejo = (RAIZ / DATA).read_text(encoding="utf-8")
    ks = lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False)  # noqa: E731
    sn, sv = {ks(r) for r in ctx.rows}, {ks(r) for r in baseline}
    cambios = f"- filas: {len(baseline)} → {len(ctx.rows)}; nuevas/modificadas: {len(sn - sv)}; quitadas: {len(sv - sn)}"
    log("\n" + cambios)
    (trabajo / "promos-semana.json").write_text(nuevo, encoding="utf-8")
    estado_igual = all(
        (RAIZ / STATE / f"{k}.json").exists()
        and json.loads((RAIZ / STATE / f"{k}.json").read_text(encoding="utf-8")) == json.loads(json.dumps(v)) for k, v in ctx.new_state.items())
    if nuevo == viejo and estado_igual:
        log("Nada para hacer: data/promos-semana.json y el estado ya coinciden con lo armado (idempotente).")
        return EXIT_OK

    if a.dry_run:
        copia = Path(tempfile.mkdtemp(prefix="promos-dry-"))
        shutil.copytree(RAIZ, copia / "repo", ignore=shutil.ignore_patterns(".git", ".promos-work", "__pycache__", ".venv", "venv", "node_modules"))
        destino = copia / "repo"
    elif a.pr:
        rama = f"promos/semana-{w0}"
        sh(["git", "fetch", "origin", a.base], RAIZ)
        ya = sh(["gh", "pr", "list", "--head", rama, "--state", "open", "--json", "url", "-q", ".[0].url"], RAIZ, check=False).stdout.strip()
        if ya:
            log(f"Ya hay un PR abierto para {rama}: {ya}. No se crea otro.")
            return EXIT_OK
        destino = trabajo / "worktree"
        if destino.exists():
            sh(["git", "worktree", "remove", "--force", str(destino)], RAIZ, check=False)
        existe = sh(["git", "rev-parse", "--verify", "--quiet", rama], RAIZ, check=False).returncode == 0
        sh(["git", "worktree", "add", *(["-B", rama, str(destino), rama] if existe else ["-b", rama, str(destino), f"origin/{a.base}"])], RAIZ)
        sh(["git", "-C", str(destino), "reset", "--hard", f"origin/{a.base}"], RAIZ)
    else:
        destino = RAIZ
    (destino / DATA).write_text(nuevo, encoding="utf-8")
    escribir_state(destino, ctx.new_state)
    log(f"[escrito] {destino / DATA} y {destino / STATE}")

    tests = "no se corrieron (--skip-tests)"
    if not a.skip_tests:
        if not correr_tests(destino):
            log("ERROR: los tests fallaron; no se commitea ni se abre PR.")
            return EXIT_TESTS
        tests = "suite completa y `BARATOYA_TESTS_REALES=1`: OK"
    if a.dry_run:
        log(f"\nDRY-RUN OK. Nada se escribió en el repo. Resultado en {trabajo.relative_to(RAIZ)}/promos-semana.json")
        shutil.rmtree(destino.parent, ignore_errors=True)
        return EXIT_OK
    if a.pr:
        sh(["git", "add", "data/promos-semana.json", "scripts/promos/state"], destino)
        if not sh(["git", "status", "--porcelain"], destino).stdout.strip():
            log("Nada para commitear.")
            return EXIT_OK
        sh(["git", "commit", "-q", "-m", f"data: promos bancarias semana {w0} al {w1}"], destino)
        sha = sh(["git", "rev-parse", "HEAD"], destino).stdout.strip()
        sh(["git", "push", "-u", "origin", rama], destino)
        body = cuerpo_pr(w0, w1, ctx, tabla, al, cambios, tests)
        r = sh(["gh", "pr", "create", "--base", a.base, "--head", rama, "--title", f"promos: semana {w0} al {w1}", "--body", body], destino)
        log(f"PR creado (sin merge): {r.stdout.strip()}  commit {sha}")
    else:
        log("Listo en el árbol de trabajo (sin commit). Revisá `git diff` y commiteá, o usá --pr.")
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"ERROR inesperado: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(EXIT_ENTORNO)
