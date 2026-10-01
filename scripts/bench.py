"""Benchmark the pipeline on saved recordings: speed per step, retake-check accuracy, clarity.

Run through make (it uses the project's Python):
  make fixtures ARGS="tjqn57np"                      # import every recording for a link
  make fixtures ARGS="11 12 14-27"                   # ...or by recording number
  make bench                                         # benchmark every fixture
  make bench ARGS="--good --only r17,r20"            # a subset
  make bench ARGS="--set CROSSFADE_MS=12"            # try a setting without editing .env
  make bench ARGS="--save-baseline"                  # make this run the one to compare against
  make bench ARGS="--good --reuse-analysis --set PLAYBACK_SPEED=0.8"
                                                     # quality sweeps in seconds (timings not comparable)

Fixtures live in backend/tests/fixtures/ and are git-ignored: they're your face and voice.
Each run is saved to data/bench/<time>/ with the output videos, so you can watch them.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from _env import require_project_python  # noqa: E402

require_project_python()

from app import config  # noqa: E402
from app.core import cadence, pipeline, scoring  # noqa: E402

FIXTURES = config.ROOT / "backend" / "tests" / "fixtures"
MANIFEST = FIXTURES / "manifest.json"
BENCH_DIR = config.DATA_DIR / "bench"
BASELINE = BENCH_DIR / "baseline.json"


# ── import ─────────────────────────────────────────────────────────────────────


def _parse_ids(specs: list[str], db: sqlite3.Connection | None = None) -> list[int]:
    """Recording numbers ("11", "14-27", "20,22") or link ids ("tjqn57np": all its recordings)."""
    ids: list[int] = []
    for spec in specs:
        for part in spec.split(","):
            if not part:
                continue
            if re.fullmatch(r"\d+-\d+", part):
                a, b = part.split("-")
                ids.extend(range(int(a), int(b) + 1))
            elif part.isdigit():
                ids.append(int(part))
            elif db is not None:
                found = [r[0] for r in db.execute(
                    "select r.id from recording r join challenge c on c.id = r.challenge_id "
                    "where c.slug = ? order by r.id", (part,))]
                if not found:
                    print(f"  {part}: no link with that id (or it has no recordings)")
                ids.extend(found)
            else:
                raise ValueError(f"not a recording number: {part}")
    return ids


def cmd_import(args: argparse.Namespace) -> None:
    db = sqlite3.connect(config.DATA_DIR / "misconstrue.db")
    fixtures = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []
    known = {f["name"] for f in fixtures}
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for rid in _parse_ids(args.ids, db):
        row = db.execute(
            "select r.status, r.input_path, r.challenge_id, c.masked_text, c.target_text, r.prompt_timings, c.slug, "
            "(select count(*) from recording r2 where r2.challenge_id = r.challenge_id and r2.id <= r.id) "
            "from recording r join challenge c on c.id = r.challenge_id where r.id = ?",
            (rid,),
        ).fetchone()
        if not row:
            print(f"  r{rid}: no such recording, skipped")
            continue
        status, input_path, _, masked, target, prompt_timings, slug, attempt = row
        src = Path(input_path)
        if not src.exists() or src.stat().st_size == 0:
            print(f"  r{rid}: video file missing or empty, skipped")
            continue
        name = f"r{rid}"
        if name in known:
            print(f"  {name}: already a fixture, skipped")
            continue
        dest = FIXTURES / f"{name}{src.suffix}"
        shutil.copy2(src, dest)
        # A take at or past the retake cap was rendered without being checked, so its label
        # can't be trusted: leave it for a human to decide.
        forced = attempt >= config.MAX_RETAKES
        expected = None if forced else ("good" if status == "done" else "bad" if status == "needs_retake" else None)
        fixtures.append({
            "name": name,
            "video": dest.name,
            "masked_text": masked,
            "target_text": target,
            "prompt_timings": prompt_timings or "",
            "slug": slug,
            "expected": expected,
            "note": f"attempt {attempt}" + (", rendered after hitting the retake cap: label me" if forced else ""),
        })
        print(f"  {name}: {expected or 'UNLABELLED'} ({src.stat().st_size // 1024} KB)")
    MANIFEST.write_text(json.dumps(fixtures, indent=2) + "\n")
    print(f"{len(fixtures)} fixtures in {MANIFEST.relative_to(config.ROOT)}")


# ── run ────────────────────────────────────────────────────────────────────────


def _apply_overrides(pairs: list[str]) -> dict[str, str]:
    applied = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        if key not in config.Settings.model_fields:
            raise SystemExit(f"Unknown setting {key}")
        setattr(config.settings, key, value)  # validated, like .env
        applied[key] = value
    return applied


def _select(fixtures: list[dict], args: argparse.Namespace) -> list[dict]:
    if args.only:
        wanted = set(args.only.split(","))
        fixtures = [f for f in fixtures if f["name"] in wanted]
    if args.good:
        fixtures = [f for f in fixtures if f["expected"] == "good"]
    if args.bad:
        fixtures = [f for f in fixtures if f["expected"] == "bad"]
    return fixtures


ANALYSIS_CACHE = BENCH_DIR / "analysis"
REFERENCES = FIXTURES / "reference"
_reference_times: dict[str, cadence.WordTimes] = {}


def _reference_for(fx: dict) -> cadence.WordTimes | None:
    """Word timings of the link's reference voice (recorded on the tuning page), if there is one."""
    slug = fx.get("slug")
    if not slug:
        return None
    if slug not in _reference_times:
        path = next((p for p in sorted(REFERENCES.glob(f"{slug}.*"))), None)
        try:
            _reference_times[slug] = cadence.word_times(path, fx["target_text"]) if path else None
        except Exception as exc:  # an unusable reference shouldn't stop the benchmark
            print(f"  (couldn't time the reference for {slug}: {exc})")
            _reference_times[slug] = None
    return _reference_times[slug]


def _run_one(fx: dict, out_dir: Path, reuse_analysis: bool) -> dict:
    out = out_dir / f"{fx['name']}.mp4"
    if reuse_analysis:
        work = ANALYSIS_CACHE / fx["name"]
        work.mkdir(parents=True, exist_ok=True)
        res = pipeline.run(FIXTURES / fx["video"], fx["masked_text"], fx["target_text"], work, out,
                           prompt_timings=fx.get("prompt_timings"))
    else:
        with tempfile.TemporaryDirectory(prefix="bench_") as tmp:
            res = pipeline.run(FIXTURES / fx["video"], fx["masked_text"], fx["target_text"], Path(tmp), out,
                               prompt_timings=fx.get("prompt_timings"))
    got = "good" if res.status == "done" else "bad" if res.status == "needs_retake" else res.status
    row = {
        "name": fx["name"],
        "expected": fx["expected"],
        "got": got,
        "correct": None if fx["expected"] is None else got == fx["expected"],
        "timings": res.timings,
        "message": res.message,
    }
    if res.output:
        c = scoring.clarity(res.output, fx["target_text"])
        row.update(clarity=c.score, sounds=c.sounds, heard=c.heard, output=out.name)
        ref = _reference_for(fx)
        if ref:
            row["cadence_plain"] = cadence.compare(ref, cadence.word_times(res.output, fx["target_text"]))
            if res.party_words:
                row["cadence_party"] = cadence.compare(ref, res.party_words)
    return row


def _fmt_delta(new: float | None, old: float | None, unit: str, better_lower: bool) -> str:
    if new is None or old is None:
        return ""
    d = new - old
    # Timings wobble by a few percent between identical runs; don't call that a change.
    if (unit == "s" and abs(d) < max(0.5, 0.1 * old)) or (unit == "%" and abs(d) < 0.005):
        return "  ="
    good = (d < 0) == better_lower
    sign = "+" if d > 0 else "−"
    val = f"{abs(d):.1f}s" if unit == "s" else f"{abs(d) * 100:.0f}%"
    return f" {sign}{val} {'✓' if good else '✗'}"


def _print_table(rows: list[dict], baseline: dict | None) -> None:
    base = {r["name"]: r for r in (baseline or {}).get("rows", [])}
    print(f"\n{'fixture':8} {'expect':7} {'got':5} {'ok':3} {'total':>7} {'align':>7} {'words':>6} {'sounds':>7}  heard")
    print("─" * 100)
    for r in rows:
        b = base.get(r["name"], {})
        ok = {True: "✓", False: "✗", None: "?"}[r["correct"]]
        total = r["timings"].get("total")
        align = r["timings"].get("align")
        clar = r.get("clarity")
        snd = r.get("sounds")
        print(
            f"{r['name']:8} {r['expected'] or '-':7} {r['got']:5} {ok:3} "
            f"{total:6.1f}s {(f'{align:6.1f}s' if align is not None else '      -'):>7} "
            f"{(f'{clar * 100:5.0f}%' if clar is not None else '     -'):>6} "
            f"{(f'{snd * 100:6.0f}%' if snd is not None else '      -'):>7}  "
            f"{(r.get('heard') or r['message'])[:48]}"
        )
        deltas = (_fmt_delta(total, b.get("timings", {}).get("total"), "s", True)
                  + (" words" + d if (d := _fmt_delta(clar, b.get("clarity"), "%", False)) else "")
                  + (" sounds" + d if (d := _fmt_delta(snd, b.get("sounds"), "%", False)) else ""))
        if deltas.strip():
            print(f"{'':8} vs baseline:{deltas}")
        for version in ("plain", "party"):
            if r.get(f"cadence_{version}"):
                print(f"{'':8} cadence ({version}): {cadence.summary(r[f'cadence_{version}'])}")


def _summary(rows: list[dict]) -> dict:
    labelled = [r for r in rows if r["correct"] is not None]
    rendered = [r for r in rows if r.get("clarity") is not None]
    step_names = sorted({k for r in rendered for k in r["timings"]})
    return {
        "check_correct": sum(r["correct"] for r in labelled),
        "check_labelled": len(labelled),
        "mean_clarity": round(statistics.mean(r["clarity"] for r in rendered), 3) if rendered else None,
        "mean_sounds": round(statistics.mean(r.get("sounds", 0) for r in rendered), 3) if rendered else None,
        "mean_steps_rendered": {
            k: round(statistics.mean(r["timings"].get(k, 0) for r in rendered), 2) for k in step_names
        },
        "rendered": len(rendered),
    }


def _print_summary(s: dict, baseline: dict | None) -> None:
    b = (baseline or {}).get("summary", {})
    print("\nSummary")
    print(f"  retake check right:  {s['check_correct']}/{s['check_labelled']} labelled fixtures"
          + (f"   (baseline {b['check_correct']}/{b['check_labelled']})" if b else ""))
    if s["mean_clarity"] is not None:
        print(f"  clarity (words):     {s['mean_clarity'] * 100:.0f}% average over {s['rendered']} videos"
              + _fmt_delta(s["mean_clarity"], b.get("mean_clarity"), "%", False))
        print(f"  clarity (sounds):    {s['mean_sounds'] * 100:.0f}% average"
              + _fmt_delta(s["mean_sounds"], b.get("mean_sounds"), "%", False))
        steps = s["mean_steps_rendered"]
        bsteps = b.get("mean_steps_rendered", {})
        order = ["normalise", "transcribe", "align", "plan", "render", "total"]
        print("  mean time per rendered video:")
        for k in sorted(steps, key=lambda k: order.index(k) if k in order else 99):
            print(f"    {k:12} {steps[k]:6.1f}s" + _fmt_delta(steps[k], bsteps.get(k), "s", True))


def cmd_run(args: argparse.Namespace) -> None:
    if not MANIFEST.exists():
        raise SystemExit("No fixtures yet. Import some with: make fixtures ARGS=\"<link id or recording numbers>\"")
    overrides = _apply_overrides(args.set)
    fixtures = _select(json.loads(MANIFEST.read_text()), args)
    if not fixtures:
        raise SystemExit("No fixtures match")

    out_dir = BENCH_DIR / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True)
    print(f"Running {len(fixtures)} fixtures → {out_dir.relative_to(config.ROOT)}")
    if overrides:
        print("Overrides: " + ", ".join(f"{k}={v}" for k, v in overrides.items()))
    if args.reuse_analysis:
        print("Reusing saved analysis: clarity is comparable, timings are not.")

    rows = []
    for i, fx in enumerate(fixtures, 1):
        print(f"  [{i}/{len(fixtures)}] {fx['name']}…", end="", flush=True)
        row = _run_one(fx, out_dir, args.reuse_analysis)
        print(f" {row['got']} in {row['timings']['total']:.1f}s")
        rows.append(row)

    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() and not args.save_baseline else None
    if baseline:
        # Compare like with like: only the fixtures both runs have.
        names = {f["name"] for f in fixtures}
        common = [r for r in baseline["rows"] if r["name"] in names]
        if len(common) != len(baseline["rows"]) or len(common) != len(fixtures):
            print(f"(comparing with the baseline on the {len(common)} fixture(s) both runs have)")
        baseline = {**baseline, "rows": common, "summary": _summary(common)} if common else None
    result = {
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fixtures": [f["name"] for f in fixtures],
        "settings_changed": {k: str(v) for k, v in config.changed().items()},
        "reused_analysis": args.reuse_analysis,
        "rows": rows,
        "summary": _summary(rows),
    }
    (out_dir / "results.json").write_text(json.dumps(result, indent=2) + "\n")

    _print_table(rows, baseline)
    if baseline and len(baseline["rows"]) != len(rows):
        # Summaries must cover the same fixtures to be comparable.
        common = {r["name"] for r in baseline["rows"]}
        print(f"\n(summary below covers the {len(common)} fixture(s) both runs have)")
        _print_summary(_summary([r for r in rows if r["name"] in common]), baseline)
    else:
        _print_summary(result["summary"], baseline)
    if args.save_baseline:
        BASELINE.write_text(json.dumps(result, indent=2) + "\n")
        print(f"\nSaved as the baseline ({BASELINE.relative_to(config.ROOT)})")
    elif not baseline:
        print("\nNo baseline yet: add --save-baseline to compare future runs against this one.")
    print(f"Videos + results: {out_dir.relative_to(config.ROOT)}")


def main() -> None:
    import logging

    logging.basicConfig(level=logging.WARNING)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(required=True)

    imp = sub.add_parser("import", help="copy app recordings into the fixtures folder")
    imp.add_argument("ids", nargs="+", help="link ids (e.g. tjqn57np) or recording numbers (e.g. 11 12 14-27)")
    imp.set_defaults(func=cmd_import)

    run = sub.add_parser("run", help="benchmark the fixtures")
    run.add_argument("--only", help="comma-separated fixture names, e.g. r17,r20")
    run.add_argument("--good", action="store_true", help="only fixtures labelled good")
    run.add_argument("--bad", action="store_true", help="only fixtures labelled bad")
    run.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a setting")
    run.add_argument("--save-baseline", action="store_true", help="save this run as the baseline")
    run.add_argument("--reuse-analysis", action="store_true",
                     help="keep each fixture's analysis between runs: fast quality comparisons, timings not comparable")
    run.set_defaults(func=cmd_run)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
