"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems = [f"PR {p}" for p in _report_problems(pr, spec, full=True)]
    # The baseline is evidence too: a poisoned baseline makes every "no significant drop" pass.
    problems += [f"baseline {p}" for p in _report_problems(base, spec, full=False)]

    # Same (item, seed) set and same per-item slice tags as the baseline.
    pk, bk = _keys(pr), _keys(base)
    if pk != bk:
        extra, gone = sorted(pk - bk), sorted(bk - pk)
        problems.append(f"(item, seed) set differs from baseline: {len(gone)} missing {gone[:5]}, "
                        f"{len(extra)} extra {extra[:5]}")
    if sorted(pr["manifest"].get("seeds") or []) != sorted(base["manifest"].get("seeds") or []):
        problems.append(f"seeds {pr['manifest'].get('seeds')} != baseline {base['manifest'].get('seeds')}")
    ps, bsl = _slice_tags(pr), _slice_tags(base)
    for item in sorted(set(ps) & set(bsl)):
        if ps[item] != bsl[item]:
            problems.append(f"{item}: slice tags {sorted(ps[item])} != baseline {sorted(bsl[item])}")
    # Slice tags must also match the eval set they were built from (both reports relabelled = still wrong).
    problems += _slices_vs_eval_set(pr, spec)

    if base_spec is not None:
        problems += ratchet_problems(spec, base_spec)
    return problems


def _keys(rep: dict) -> set[tuple[str, int]]:
    return {(r.get("item_id"), r.get("seed")) for r in rep.get("rows") or []}


def _slice_tags(rep: dict) -> dict[str, frozenset]:
    """item -> slice tags; an item whose seeds disagree on tags gets a sentinel so it never matches."""
    out: dict[str, frozenset] = {}
    for r in rep.get("rows") or []:
        tags = frozenset(r.get("slices") or [])
        prev = out.setdefault(r.get("item_id"), tags)
        if prev != tags:
            out[r.get("item_id")] = frozenset({"<inconsistent across seeds>"})
    return out


def _bad_number(v) -> bool:
    return isinstance(v, float) and not math.isfinite(v)


def _report_problems(rep: dict, spec: dict, full: bool) -> list[str]:
    """Checks that need only one report. full=True (the PR) also requires every graded metric on
    every row; the baseline may predate a newly added metric, which a missing value already blocks."""
    from lab9.graders import GRADERS
    probs: list[str] = []
    metrics = rep.get("metrics") or {}
    probs += [f"metric {k} = {v!r} (NaN/inf)" for k, v in metrics.items() if _bad_number(v)]
    if rep.get("evaluator_failures"):
        f = rep["evaluator_failures"]
        probs.append(f"{len(f)} evaluator failure(s), first: {str(f[0])[:80]}")
    rows = rep.get("rows") or []
    man = rep.get("manifest") or {}
    want = (man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        probs.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want}")
    if spec.get("seeds") and sorted(man.get("seeds") or []) != sorted(spec["seeds"]):
        probs.append(f"seeds {man.get('seeds')} != spec seeds {spec['seeds']}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1})
    if dups:
        probs.append(f"{len(dups)} duplicated (item, seed) row(s), first {dups[0]}")
    graded = [m["id"] for m in spec["metrics"] if m["id"] in GRADERS]
    for mid in graded:
        if not full and not any(mid in r for r in rows):
            continue
        bad = [r for r in rows if not isinstance(r.get(mid), bool)]
        if bad:
            r = bad[0]
            probs.append(f"{len(bad)} row(s) with {mid} = {r.get(mid)!r} (not graded), first "
                         f"{r.get('item_id')}@{r.get('seed')}")
    for r in rows:
        if _bad_number(r.get("cost")):
            probs.append(f"{r.get('item_id')}@{r.get('seed')}: cost {r.get('cost')!r}")
            break
    # Headline numbers must be what the rows say: catches a hand-edited "metrics" block.
    ids = [m for m in graded if rows and all(isinstance(r.get(m), bool) for r in rows)]
    if rows and all("cost" in r for r in rows):
        from lab9.eval import aggregate
        again = aggregate(rows, ids, k_values=spec.get("pass_k", []))
        for k, v in metrics.items():
            if k in again and not _bad_number(v) and not _same(v, again[k]):
                probs.append(f"metric {k} = {v!r} but rows give {again[k]!r}")
    return probs


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    try:
        return abs(float(a) - float(b)) <= 5e-5
    except (TypeError, ValueError):
        return False


def _slices_vs_eval_set(pr: dict, spec: dict) -> list[str]:
    from lab9 import evalset
    path = Path(spec.get("eval_set") or "")
    if not path.is_file() or evalset.sha12(path) != pr["manifest"].get("eval_set_sha"):
        return []          # can't read the source of truth here; the baseline comparison still applies
    truth = {it["item_id"]: frozenset(it.get("slices") or []) for it in evalset.load_jsonl(path)}
    out = []
    for item, tags in sorted(_slice_tags(pr).items()):
        if item in truth and tags != truth[item]:
            out.append(f"{item}: slice tags {sorted(tags)} != eval set {sorted(truth[item])}")
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => thresholds may only get stricter. A new eval-set version starts a
    new baseline, so the ratchet restarts there."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    out: list[str] = []
    for key in ("eval_set", "labels", "adversarial_pack"):
        if spec.get(key) != base_spec.get(key):
            out.append(f"ratchet: {key} {spec.get(key)!r} != base {base_spec.get(key)!r}")
    if set(base_spec.get("seeds") or []) - set(spec.get("seeds") or []):
        out.append(f"ratchet: seeds {spec.get('seeds')} drop some of base {base_spec.get('seeds')}")
    if set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or []):
        out.append(f"ratchet: pass_k {spec.get('pass_k')} drops some of base {base_spec.get('pass_k')}")
    bb, sb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if sb.get("n_resamples", 1000) < bb.get("n_resamples", 1000):
        out.append("ratchet: bootstrap n_resamples lowered")
    if sb.get("confidence", 0.95) < bb.get("confidence", 0.95):
        out.append("ratchet: bootstrap confidence lowered")

    def rules(name: str, old: dict, new: dict | None, old_th: dict, new_th: dict) -> list[str]:
        if new is None:
            return [f"ratchet: {name} removed"]
        r = []
        if old.get("blocking") and not new.get("blocking"):
            r.append(f"ratchet: {name} no longer blocking")
        if old.get("kind") and new.get("kind") != old.get("kind"):
            r.append(f"ratchet: {name} kind {old.get('kind')} -> {new.get('kind')}")
        for k in ("max", "max_increase"):
            if k in old_th and (k not in new_th or new_th[k] > old_th[k]):
                r.append(f"ratchet: {name} {k} {old_th[k]} -> {new_th.get(k)}")
        if "min" in old_th and ("min" not in new_th or new_th["min"] < old_th["min"]):
            r.append(f"ratchet: {name} min {old_th['min']} -> {new_th.get('min')}")
        if old_th.get("no_significant_drop") and not new_th.get("no_significant_drop"):
            r.append(f"ratchet: {name} dropped no_significant_drop")
        return r

    new_m = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        n = new_m.get(m["id"])
        out += rules(m["id"], m, n, m.get("threshold") or {}, (n or {}).get("threshold") or {})
    new_s = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        n = new_s.get((s["name"], s["metric"]))
        out += rules(f"slice:{s['name']}/{s['metric']}", s, n, s, n or {})
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a = per_item(pr, metric, slice_name=name)
        b = per_item(base, metric, slice_name=name)
        verdict, note = "ok", ""
        if not a:
            # A slice with no rows cannot vouch for anything: treat as missing, not as a pass.
            verdict, val = "missing", None
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if s.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}] n={len(keys)}"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<40} {note:<34} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
