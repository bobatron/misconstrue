# misconstrue backlog

Small, independently shippable work items. Sizes: **S** ≈ under an hour, **M** ≈ a few hours,
**L** ≈ a day or more. Priority: **P0** do next · **P1** soon · **P2** later · **P3** hosting / someday.

## Summary

| ID | Item | Area | Size | Priority | Depends on |
|---|---|---|---|---|---|
| BUG-1 | Turn camera & mic off after submitting | Bug | S | **P0** | — |
| CONFIG-1 | Editable settings file (`.env`) | Tooling | S | **P0** | — |
| TOOL-1 | Benchmark + intelligibility test harness | Tooling | M | **P0** | — |
| CONFIG-2 | Tuning page: live settings + re-render a saved recording | Tooling | M | P1 | CONFIG-1, PERF-2 (for speed) |
| PERF-1 | Mini pronunciation dictionary per recording | Performance | S | **P0** | TOOL-1 (to measure) |
| PERF-2 | Reuse MFA's cache between runs | Performance | S | P1 | PERF-1 |
| PERF-3 | Keep MFA loaded as a long-running worker | Performance | M | P2 | PERF-1 |
| PERF-4a | Spike: in-memory aligner (torchaudio + wav2vec2) | Performance | M | P2 | TOOL-1 |
| PERF-4b | Ship the in-memory aligner behind a setting | Performance | M | P3 | PERF-4a |
| PERF-5 | Load Whisper at startup, not on first upload | Performance | S | P1 | — |
| QUAL-1 | Slow down the final sentence (time-stretch) | Quality | M | **P0** | TOOL-1 |
| QUAL-2 | Short pauses between words | Quality | S | P1 | TOOL-1 |
| QUAL-3 | Prefer longer, clearer copies of each sound | Quality | S | P1 | TOOL-1 |
| QUAL-4 | Ask the reader to speak slowly and clearly | Quality | S | P1 | — |
| SYL-1 | Syllable-aware cutting | Quality | M | P1 | TOOL-1 |
| SYL-2 | Looser sound matching (stress / vowel tolerance) | Quality | M | P1 | SYL-1 |
| SYL-3 | "Secrecy level" setting: allow word-part carriers ("origin" + "lee") | Quality | M | P1 | SYL-2 |
| POL-1 | Tune the completeness check on real recordings | Polish | M | P2 | TOOL-1 |
| POL-2 | Safari / iPhone recording support | Polish | M | P2 | — |
| POL-3 | Better masked sentences (fewer word-list fallbacks) | Polish | M | P2 | — |
| POL-4 | Carrier word clean-up (names like "Boston", odd words) | Polish | S | P2 | — |
| POL-5 | Friendlier error & edge-case screens | Polish | S | P2 | — |
| POL-6 | Loudness & crossfade tuning | Polish | S | P2 | TOOL-1 |
| HOST-1 | Dockerfile + docker-compose | Hosting | M | P3 | — |
| HOST-2 | CI: run tests on every push (GitHub Actions) | Hosting | S | P3 | — |
| HOST-3 | Proper job queue instead of an in-process thread | Hosting | M | P3 | HOST-1 |
| HOST-4 | Store videos in object storage (S3-compatible) | Hosting | M | P3 | HOST-1 |
| HOST-5 | Auto-delete old recordings (retention) | Hosting | S | P3 | — |
| HOST-6 | Rate limiting & upload limits | Hosting | S | P3 | — |
| HOST-7 | Consent / "this is a prank" notice | Hosting | S | P3 | — |
| HOST-8 | LLM on the server (hosted model or GPU box) | Hosting | M | P3 | HOST-1 |
| HOST-9 | Choose a host, deploy with HTTPS & a domain | Hosting | M | P3 | HOST-1…8, HOST-10 |
| HOST-10 | Lock down the tuning page (password or disabled) | Hosting | S | P3 | CONFIG-2 |

**Suggested order:** BUG-1 → CONFIG-1 → TOOL-1 → PERF-1 → CONFIG-2 → QUAL-1 → QUAL-4 → SYL-1 → SYL-2 → SYL-3 → PERF-2 → the rest.

---

## Bug

### BUG-1 · Turn camera & mic off after submitting  `S · P0`
**Problem:** after User 2 presses Submit, the browser tab (and the device's indicator) still
shows the camera and microphone as in use.
**Cause:** the page keeps the camera stream open until it closes, so that retakes can
start immediately.
**Do:**
- Stop all camera/mic tracks as soon as Submit is pressed.
- If the check asks for a retake, turn the camera back on automatically (the browser won't
  ask again, since permission was already given).
- Also stop the tracks on the reveal, error and "link not found" screens, and when leaving the page.
**Done when:** the camera light/tab indicator goes off on Submit, in both Chrome and Safari;
retakes still work.

---

## Tooling

### TOOL-1 · Benchmark + intelligibility test harness  `M · P0`
The foundation for tuning speed and quality without guessing.
**Do:**
- Save a set of reference recordings in `backend/tests/fixtures/` (your real takes, good and
  deliberately bad), each with its masked and target sentences.
- `scripts/bench.py`: runs each through the pipeline and reports **time per step**, plus an
  **intelligibility score**: Whisper transcribes the *output* video and we measure how
  close it is to the target sentence (word error rate).
- Prints a before/after table so every change below can prove it helped.
**Done when:** one command prints timing + intelligibility for all fixtures.

### CONFIG-1 · Editable settings file  `S · P0`
**Do:**
- Load settings from a `.env` file at the project root (git-ignored), with a committed
  `.env.example` listing every setting, grouped (masking / retake check / output video) and
  commented in plain English, e.g. "higher = stricter".
- Validate values on startup and print the settings in use.
**Done when:** changing a value in `.env` and restarting changes the app's behaviour.

### CONFIG-2 · Tuning page  `M · P1`
**Do:**
- A `/tune` page (local only) with sliders and switches for each setting, grouped as above.
  Changes are saved (`data/settings.json`) and apply to the next video without a restart.
- **Re-render:** pick an existing recording, change settings, remake its video without
  recording again. Reuse the saved transcript and alignment so only the edit step reruns
  (≈ 2 s).
- **Compare:** before/after videos side by side, with the settings used and the TOOL-1
  clarity score when available.
- "Reset to defaults" button.
**Done when:** you can try several playback speeds on one recording in under a minute.

---

## Performance

Measured today: ≈ 48 s per video, of which **42 s is the aligner (MFA)**, mostly start-up
cost rather than actual aligning.

### PERF-1 · Mini pronunciation dictionary per recording  `S · P0`
MFA loads its full 200,000-word dictionary on every run, but a sentence uses about 25 words.
**Do:**
- Before aligning, write a small dictionary containing only the masked sentence's words,
  copying their exact lines from the full dictionary (all pronunciation variants).
- If a word is missing from the full dictionary, fall back to the full dictionary for that run.
**Done when:** alignment ≈ 14 s (tested by hand: 42 s → 14 s), and the fixtures give identical
or equal-quality results.

### PERF-2 · Reuse MFA's cache between runs  `S · P1`
MFA caches its set-up work, but we currently wipe it after each run (`--clean`).
Tested by hand: a repeat run took 10 s instead of 43 s.
**Do:**
- Use a persistent MFA working folder under `data/mfa_cache/`, without `--clean`.
- Key the cache per link (per challenge), so retakes of the same sentence reuse it. This fits
  with PERF-1's per-sentence dictionary.
- Safe because recordings are processed one at a time; clear old caches alongside HOST-5.
**Done when:** a retake aligns in ≈ 10 s or less; no stale results between different links.

### PERF-3 · Keep MFA loaded as a long-running worker  `M · P2`
Instead of starting the `mfa` program fresh each time (paying start-up cost), load the aligner
once when the backend starts and keep it in memory.
**Do:**
- Investigate MFA's Python API (e.g. its pretrained aligner class) to load the acoustic model
  once and align single recordings on demand.
- Run it in the processing worker; fall back to the command-line tool if it fails.
**Done when:** alignment ≈ 2–5 s; total ≈ 8–10 s.
**Risk:** MFA's internal API isn't designed for this and may change between versions.

### PERF-4a · Spike: in-memory aligner (torchaudio + wav2vec2)  `M · P2`
A different aligner that runs entirely in memory and takes about a second.
**Do (time-boxed experiment):**
- Use `torchaudio.functional.forced_align` with a phoneme-recognition model.
- Map its phoneme symbols to ours (ARPAbet), or switch our dictionary to match.
- Compare cut accuracy vs MFA on the TOOL-1 fixtures.
**Done when:** a written go / no-go with numbers (speed, intelligibility score).

### PERF-4b · Ship the in-memory aligner behind a setting  `M · P3`
If PERF-4a says go: implement it behind the existing aligner interface with
`ALIGNER=mfa|wav2vec2`, keeping MFA as the fallback. Also removes the heavy MFA/conda
dependency, which makes hosting easier.

### PERF-5 · Load Whisper at startup  `S · P1`
Whisper loads on the first upload (≈ 1 s). Load it when the backend starts, like the word
index. Small, but free.

---

## Output quality: clarity

Feedback: sounds in the final video are sometimes very short, making the sentence hard to
follow. Four complementary fixes, each measurable with TOOL-1.

### QUAL-1 · Slow down the final sentence  `M · P0`
**Do:**
- Stretch the stitched audio to play slower **without changing pitch** (e.g. ffmpeg's
  `atempo`, or the Rubber Band library for better quality). Setting: `PLAYBACK_SPEED`,
  default around 0.85.
- Make the video follow: the frame chosen for each moment uses the stretched timeline, so
  lips stay in sync (frames are repeated, not blended).
- Optionally stretch only the very short pieces more than the long ones.
**Done when:** the fixtures' intelligibility score improves, and it still looks in sync.

### QUAL-2 · Short pauses between words  `S · P1`
Insert a small gap (setting `WORD_GAP_MS`, e.g. 60–120 ms) between the words of the target
sentence. The video holds the nearest frame during the pause. Pauses help the listener
find word boundaries.

### QUAL-3 · Prefer longer, clearer copies of each sound  `S · P1`
When the recording contains the same sound more than once, the planner currently only
avoids *squashed* ones. Also favour copies from stressed syllables, which are naturally
longer and clearer, and add a mild penalty for any piece shorter than about 60 ms.

### QUAL-4 · Ask the reader to speak slowly and clearly  `S · P1`
The easiest win: slower reading gives longer sounds to cut from. Add "read slowly and
clearly, like you're talking to someone far away" to the record screen. Optionally, if the
recording is very fast (sounds per second), ask for a slower retake.

---

## Output quality: syllable chunks ("origin" + "lee")

Idea: rebuild words from **bigger, natural pieces** such as syllables or parts of words,
instead of scavenging individual sounds. E.g. for "originally", have the reader say
"origin" and "lee".

Checked today, "origin" is blocked in two ways:
1. The hiding rules forbid it (it shares 6 letters with "originally").
2. Its sounds don't match exactly. The dictionary says "**OR**-i-gin" but "o-**RIG**-i-nally":
   the stress falls on different syllables, which changes the vowels. "lee" vs "-ly" has the
   same stressed/unstressed mismatch.

So this takes three steps:

### SYL-1 · Syllable-aware cutting  `M · P1`
- Split target and carrier words into syllables (standard rule: consonants join the
  following vowel where English allows).
- Make cuts at syllable boundaries cheap and cuts inside a syllable expensive, in both the
  masker and the edit-time planner.
- Prefer carriers whose piece is one or more *whole* syllables.
**Done when:** plans visibly favour syllable-sized pieces; the intelligibility score doesn't drop.

### SYL-2 · Looser sound matching  `M · P1`
- Allow a stressed vowel to stand in for an unstressed one (not the reverse), with a small
  penalty: a clear "lee" can replace an unstressed "-ly".
- Allow close vowel pairs (e.g. the "uh" sound AH0 ↔ IH0) with a penalty.
- Keep exact matches preferred; loose matches are only used when they save cuts.
**Done when:** "origin" + "lee" (or similar) can cover "originally" in a test.

### SYL-3 · "Secrecy level" setting  `M · P1`
A single setting that trades secrecy for audio quality:
- **High** (today): no shared word parts.
- **Medium**: allow carriers that share a *part* of a target word ("origin" for "originally"),
  but never the whole word, and never more than one such stem per target word.
- **Low**: allow anything except the exact target words.
Could later be a toggle on User 1's create page ("sneakier" ↔ "clearer").
**Done when:** each level produces the expected kinds of masks; TOOL-1 shows the quality
gain at Medium/Low.

---

## Polish (rest of the original Phase 4)

### POL-1 · Tune the completeness check on real recordings  `M · P2`
Use the TOOL-1 fixtures (partial, skipped word, mumbled, silence, good) as regression tests;
adjust the thresholds in `config.py` so good takes always pass and bad ones never do.

### POL-2 · Safari / iPhone recording support  `M · P2`
Test the record flow in Safari (records MP4 rather than WebM) and on an iPhone (needs HTTPS:
use a tunnel for local testing). Fix any upload, orientation or playback issues.

### POL-3 · Better masked sentences  `M · P2`
Long sentences sometimes fall back to plain word lists. Try smaller groups per phrase, a
retry with different words, a better prompt, or a different local model; measure how often
a fallback happens.

### POL-4 · Carrier word clean-up  `S · P2`
Some names still slip through (e.g. "Boston" is in the old dictionary as a card game). Use
a modern word list and extend the blocklist.

### POL-5 · Friendlier error & edge-case screens  `S · P2`
Camera denied, no microphone, upload failed mid-way, processing takes too long, link
expired: each gets a clear message and a way forward.

### POL-6 · Loudness & crossfade tuning  `S · P2`
Experiment with crossfade length and loudness matching using TOOL-1 scores.

---

## Hosting (Phase 5)

### HOST-1 · Dockerfile + docker-compose  `M · P3`
Backend image (conda/mamba base with MFA, ffmpeg, models baked in or downloaded at start),
frontend built to static files, Ollama as its own container.

### HOST-2 · CI with GitHub Actions  `S · P3`
Run the unit tests and a frontend build on every push and pull request.

### HOST-3 · Proper job queue  `M · P3`
Replace the in-process worker thread with a queue (e.g. Redis + RQ) so the web server
restarting doesn't lose jobs and processing can scale separately.

### HOST-4 · Object storage for videos  `M · P3`
Store uploads and outputs in S3-compatible storage instead of the local `data/` folder.

### HOST-5 · Auto-delete old recordings  `S · P3`
Delete videos (and MFA caches) after e.g. 7 days; tell users on the page.

### HOST-6 · Rate limiting & upload limits  `S · P3`
Limit links created and uploads per IP address; enforce maximum video length server-side.

### HOST-7 · Consent / prank notice  `S · P3`
A short, friendly notice on the record page and the reveal that the video is edited.
The output video is already watermarked.

### HOST-8 · LLM on the server  `M · P3`
A small server's CPU can't run Qwen3 8B quickly. Options: a GPU host, a smaller model, or a
hosted model via the existing `LLM_PROVIDER` setting. Decide on cost vs quality.

### HOST-10 · Lock down the tuning page  `S · P3`
Before hosting, the `/tune` page and its API must be disabled or protected by a password, so
visitors can't change settings or see other people's recordings.

### HOST-9 · Deploy  `M · P3`
Choose a host (a VPS, Fly.io, Railway…), set up HTTPS and a domain (required for camera
access), and write a short deploy guide.
