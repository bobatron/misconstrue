# Benchmark fixtures (local only)

Recordings used by `scripts/bench.py`, with `manifest.json` listing each one's masked and
target sentences and whether it's a good or bad take. They're real people's faces and
voices, so everything here except this README is git-ignored.

```sh
python scripts/bench.py import 11 12 14-27   # copy recordings from the app's database
python scripts/bench.py run                  # benchmark them
```

Labels (`"expected"` in manifest.json): `"good"` = should render a video, `"bad"` = the
retake check should reject it, `null` = unknown (the benchmark reports it without judging).
