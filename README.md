# misconstrue

A fun app: User 1 types a sentence. The app writes a different, innocent-looking
**masked sentence** and gives User 1 a share link. User 2 opens the link and records
themselves reading the masked sentence. The app then chops the recording up at the
phoneme level and plays back a video of User 2 "saying" User 1's original sentence.

## Status
Working MVP. Planned work: [docs/BACKLOG.md](docs/BACKLOG.md).

- [x] Phase 0 — repo + environment setup
- [x] Phase 1 — CLI risk spike: phonetics, masking, alignment, splicing
- [x] Phase 2 — local LLM (Ollama) masking
- [x] Phase 3 — web app (FastAPI + React) with retake detection
- [ ] Phase 4 — polish
- [ ] Phase 5 — hosting

## Stack
- Backend: Python 3.11, FastAPI, SQLite, ffmpeg, Montreal Forced Aligner, faster-whisper
- Masking: CMUdict phonetics + a local LLM via [Ollama](https://ollama.com) (free, runs on your machine)
- Frontend: React + Vite + TypeScript, browser `MediaRecorder`

## Running locally (macOS)
Prerequisites: Homebrew, `brew install ffmpeg ollama && brew install --cask miniforge`, Node 20+.

```sh
brew services start ollama
make setup   # conda env, aligner models, NLTK data, qwen3:8b, npm install
make dev     # API on :8000, web app on http://localhost:5173
make test
```

Open http://localhost:5173, type a sentence, and open the link it gives you (in another
window, or send it to a friend on the same machine for now).

### Settings
The quickest way to tune is the **tuning page** at http://localhost:5173/tune: change settings,
re-render any saved recording in a couple of seconds, and compare the results side by side.

Every tunable value (how strict the retake check is, crossfade length, which AI model…) is
listed with a plain-English explanation in [`.env.example`](.env.example). To change one,
copy it to `.env`, uncomment the line, edit it and restart `make dev`. `make settings` shows
what's in use, with your changes marked.

### Benchmark
`make bench` runs your saved recordings (local only, see
[`backend/tests/fixtures/README.md`](backend/tests/fixtures/README.md)) through the pipeline
and reports time per step, whether the retake check made the right call, and a clarity
score for each output video, compared against a saved baseline. Try a setting without
editing `.env`: `make bench ARGS="--good --set CROSSFADE_MS=12"`.

### Command line
Use the `make` commands: they run the project's own Python environment. (The Mac's built-in
`python3` doesn't have the project's libraries.)

```sh
make cli ARGS='mask "hello sir this is not what I originally said"'
make cli ARGS='synth "<masked sentence>" clip.mp4'   # fake recording with macOS say
make cli ARGS='run clip.mp4 --masked "<masked sentence>" --target "hello sir..." -o out.mp4'
```

## How it works
Full plain-English explanation: [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md)

1. **Masking** — the target is turned into phonemes (MFA's ARPAbet dictionary, stress-aware).
   A dynamic program splits it into as few chunks as possible, each found inside some common
   "carrier" word that doesn't give the game away. A local LLM hides the carrier words in
   natural phrases; every candidate is re-checked to make sure it still covers every sound.
2. **Completeness gate** — Whisper transcribes the upload and compares it with the masked
   sentence (sound-alike matching). Missing words the edit needs → "please read it again",
   with those words highlighted.
3. **Alignment** — Montreal Forced Aligner gives phone-level timestamps.
4. **Editing** — the splice plan is re-run on the phones actually recorded (avoiding squashed
   alignments, preferring matching neighbours), cuts are snapped to quiet points,
   crossfaded and loudness-matched; video frames follow the audio.
