# How misconstrue works

A plain-English tour of the app: what happens at each step, which tools do the work,
and where everything runs.

---

## The big picture

```
 User 1                         the app                               User 2
 ──────                         ───────                               ──────
 types "I love pizza"  ──►  1. MASK: write a different sentence
                               with the same sounds hidden inside
                               "Watson found peace while exploring
                                the island. Government provides..."
 gets a share link    ◄──      saved with a random link id

                                                      opens the link ◄──
                                                      reads the masked
                                                      sentence on camera
                        2. CHECK: did they read all of it?  ◄── uploads video
                           no  → "we didn't catch 'island'…" ──► records again
                           yes ↓
                        3. ALIGN: find exactly when each
                           individual sound was spoken
                        4. EDIT: cut out the needed sounds,
                           stitch them in a new order
                           → video of them saying
                             "I love pizza"            ──► the reveal 🎉
```

Two programs run while you use it:

| Program | What it is | Where |
|---|---|---|
| **Frontend** | The web pages (React). Runs in the browser, including the camera recording. | `frontend/`, served on http://localhost:5173 |
| **Backend** | A Python web server (FastAPI) that does all the heavy lifting. | `backend/`, on http://localhost:8000 |

The frontend talks to the backend through a small API (`/api/...`). Everything is stored
in `data/`: a SQLite database file plus the uploaded and finished videos.

---

## The key idea: sounds, not words

Words are made of **phonemes**, the individual sounds of speech. "pizza" is four:

```
pizza  =  P  IY  T  S  AH
          p  ee  t  s  uh
```

The app never hunts for whole words. It hunts for **runs of sounds** that turn up inside
other, innocent words:

```
"I love pizza"   =   AY L  |  AH V  |  P IY T  |  S AH
                      ↑        ↑        ↑          ↑
                   h-igh-ly  sh-ove   Pete's    Watson
```

If User 2 reads "highly", "shove", "Pete's" and "Watson", every sound needed for
"I love pizza" gets recorded. It only has to be cut out and put back in the right order.

Pronunciations come from a big pronunciation dictionary: about 200,000 words, each with
its sounds listed (`~/Documents/MFA/pretrained_models/dictionary/`). It's the same
dictionary the aligner uses later, so what we plan to cut is what the aligner will find.

---

## Step 1: Masking (making the disguise)

Code: `backend/app/core/masker.py`, `phonetics.py`, `splice.py`, `llm.py`

1. **Turn the sentence into sounds** using the dictionary.
2. **Find "carrier" words.** An index maps every short run of sounds to common English
   words that contain it. A little optimiser splits the sentence into as **few** runs as
   possible, because fewer cuts sound smoother, and picks a carrier word for each run.
3. **Don't give the game away.** Carrier words are rejected if they are:
   - one of the target words, or a sound-alike ("red" for "read")
   - too close in spelling ("original" / "aboriginal" for "originally")
   - names, abbreviations, or anything on a blocklist of unpleasant words
   - words people pronounce more than one way, when the difference matters
4. **Make it read naturally.** A local AI language model (see *Ollama* below) gets small
   groups of carrier words and is asked for short, casual phrases using them. It can handle
   2–3 groups at a time, so a long sentence becomes a few phrases. The phrases are
   shuffled so their order doesn't mirror the original sentence.
5. **Double-check.** The AI can make mistakes, such as changing a word or adding a banned
   one, so every phrase is re-checked in code. If a phrase fails, that group falls back to
   a plain list of carrier words. The app always ends up with a sentence that covers every
   sound.

### Where Ollama fits in (and why there's no Docker container)

[Ollama](https://ollama.com) is a free program that runs open-source AI models on your own
computer. No account, no API key, no cost per request.

It was installed with **Homebrew** (`brew install ollama`) and runs as a normal macOS
background service, not in Docker:

```sh
brew services list          # shows "ollama  started"
brew services stop ollama   # turn it off (frees memory)
brew services start ollama  # turn it back on
ollama list                 # models you've downloaded
```

- It listens on `http://localhost:11434`; the backend sends it a request when you create a link.
- The model is **Qwen3 8B** (about 5 GB, stored in `~/.ollama/models`). Your M2 Max runs it on
  its GPU, which takes a few seconds per request.
- Ollama *can* run in Docker, and that's how we'd probably ship it to a server. On a Mac,
  though, Docker can't use the Apple GPU, so the native install is much faster locally.
- If Ollama isn't running, the app still works: it just uses the plain word-list sentence.

---

## Step 2: The completeness check ("please read it again")

Code: `backend/app/core/verify_read.py`

This is why your bad takes were rejected.

1. **Transcribe.** [Whisper](https://github.com/SYSTRAN/faster-whisper), OpenAI's speech
   recognition model, runs locally and writes down what was actually said. It is
   deliberately *not* told what the sentence should be, so it can't "hear" words that
   were never spoken.
2. **Compare.** The transcript is lined up against the masked sentence **by sound**, so
   "read"/"red" or "1"/"one" still count, and near-misses like "forward" for
   "forehead" are accepted.
3. **Only the important words must be there.** The app knows which words it will cut
   sounds from. If one of those is missing, it asks for a retake and highlights the
   missing words. A slip in a word it doesn't need is forgiven.
4. **Extra safety checks** (after alignment): each important word must have been spoken
   at a sensible speed and at roughly the time Whisper heard it. Otherwise the recording
   probably doesn't match the text.

Silence gets its own message, and after 5 attempts the app renders what it can instead of
asking forever.

---

## Step 3: Alignment (finding every sound's timestamp)

Code: `backend/app/core/aligner.py`

The [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io) (MFA) takes the
audio plus the text that was read and works out **exactly when each sound starts and
stops**, to within about 10 milliseconds:

```
 "shove"      SH          AH           V
           |--------|-------------|--------|
          3.85s    3.91s         3.99s    4.05s
```

"Forced" means it already knows the words and only has to place them in time, which is far
more precise than transcribing from scratch.

---

## Step 4: Editing (the cut-and-stitch)

Code: `backend/app/core/splice.py`, `editor.py`, `media.py`

1. **Re-plan using what was actually recorded.** The plan from Step 1 is recomputed using
   the sounds the aligner really found, because people don't always say words the way the
   dictionary does. When choosing between several recorded copies of a sound, it prefers:
   - long runs, meaning fewer cuts
   - cuts at natural break points (between words, or just before a "p/t/k" sound, which
     starts with a tiny silence)
   - copies whose neighbouring sounds match the target (an "L" before "ee" sounds different
     from an "L" before "uh")
   - copies that weren't squashed, since squashed timing usually means an alignment error
2. **Cut the audio.** Each cut point is nudged (by up to 15 ms) to the quietest nearby
   moment. Pieces overlap by 8 ms with a quick fade (a crossfade), so there are no clicks,
   and their volumes are evened out.
3. **Make the video follow the audio.** For every frame of the output, the app shows the
   frame of the original recording from the moment the current sound was spoken. That
   keeps the lips in sync with the audio. The jumpy look is part of the fun.
4. **Finish.** [ffmpeg](https://ffmpeg.org) (a video toolkit) encodes the final MP4 and adds
   the "misconstrued" watermark.

---

## How long does it take?

About **18 seconds** per video (averaged over 9 of your recordings with `make bench`):

| Step | Before PERF-1 | Now |
|---|---|---|
| Convert the upload (ffmpeg) | 0.8 s | 0.7 s |
| Run Whisper (the check) | 2.5 s | 2.2 s |
| **Align (MFA)** | **43.3 s** | **13.9 s** |
| Plan the cuts | < 0.1 s | < 0.1 s |
| Build the video | 1.6 s | 1.3 s |
| **Total** | **48.4 s** | **18.4 s** |

The big win came from giving MFA a **mini dictionary** with only the sentence's words:
it was spending most of its time loading all 200,000 words. Alignment is still most of the
wait, and there are further options, from easiest to biggest:

| Option | Effort | Expected total |
|---|---|---|
| ✅ **Mini dictionary** with only the sentence's words (done: 48 s → 18 s) | Small | 18 s |
| Keep MFA's cache between runs. *Tested: a repeat run took 10 s.* Could be combined with the above. | Small | ~15 s |
| Keep MFA loaded in memory as a long-running worker, instead of starting it fresh each time | Medium | ~5–8 s |
| Swap MFA for an in-memory aligner (torchaudio + a wav2vec2 speech model) | Larger | ~3–5 s |

The first two are low-risk and would roughly halve or third the wait.

---

## What runs where

Everything runs on your Mac. Nothing is sent to the internet while you use the app.

| Piece | Installed with | Stored in |
|---|---|---|
| Python 3.11 + backend libraries + MFA | Miniforge / conda (`make setup`) | `/opt/homebrew/Caskroom/miniforge/base/envs/misconstrue` |
| Ollama + Qwen3 8B | Homebrew | `~/.ollama/models` (4.9 GB) |
| MFA dictionary + acoustic model | `mfa model download` | `~/Documents/MFA` (95 MB) |
| Whisper `small.en` model | downloaded automatically on first use | `~/.cache/huggingface` (464 MB) |
| ffmpeg | Homebrew | — |
| Your recordings, videos, database | the app | `data/` (not committed to git) |

## Changing settings

All the tunable numbers live in one place, `backend/app/config.py`, and are listed with a
plain-English explanation and allowed range in `.env.example` at the project root.

```sh
cp .env.example .env     # then uncomment and edit the lines you want to change
make dev                 # restart to apply
make settings            # see what's in use; your changes are marked with *
```

Typos and out-of-range values stop the app at startup with a clear message (e.g.
"MAX_RETAKE: did you mean MAX_RETAKES?"), so a mistake is never silently ignored. An
environment variable with the same name overrides `.env`.

## Measuring changes (the benchmark)

Tuning by ear is unreliable, so `make bench` measures instead. It runs saved recordings
through the whole pipeline and reports, for each one:

- **Time per step:** convert, transcribe, align, plan, render.
- **Was the retake check right?** Each recording is labelled "good" (should make a video) or
  "bad" (should be rejected).
- **Clarity score:** Whisper listens to the *finished* video, and we count how many words
  of the intended sentence it heard correctly (sound-alikes like "I"/"eye" count). 100% =
  every word understood.

Results are compared against a saved **baseline**, marked ✓ (better) or ✗ (worse), and the
output videos are kept in `data/bench/<time>/` so you can watch them.

```sh
make bench                                          # everything
make bench ARGS="--good"                            # only takes that should render
make bench ARGS="--set CROSSFADE_MS=12"             # try a setting without editing .env
make bench ARGS="--save-baseline"                   # make this run the new reference
python scripts/bench.py import 30 31                # add new recordings as fixtures
```

The recordings stay on your computer (git-ignored), because they're people's faces and voices.

Whisper is a stand-in for a human listener: it's consistent and quick, but a person may
hear a video differently. Treat the score as a guide, and watch the videos too.

## Map of the code

```
backend/app/
  main.py            starts the web server
  api/routes.py      the API: create link, upload, check status, serve video
  models.py          database tables (Challenge = a link, Recording = an upload)
  config.py          all the tunable settings (defaults, .env loading, validation)
  core/
    phonetics.py     words → sounds; the carrier-word index
    masker.py        builds the masked sentence
    llm.py           talks to Ollama
    splice.py        the optimiser that decides which pieces to cut
    verify_read.py   the "did they read it all?" check (Whisper)
    aligner.py       runs MFA to get sound timings
    editor.py        cuts, crossfades, and assembles the new video
    media.py         ffmpeg helpers
    pipeline.py      runs steps 2–4 in order, timing each step
    scoring.py       clarity score for a finished video
frontend/src/
  pages/CreatePage.tsx   User 1: type a sentence, get a link
  pages/RecordPage.tsx   User 2: camera, teleprompter, retakes, reveal
scripts/cli.py         run everything from the terminal (handy for testing)
scripts/bench.py       benchmark: speed, retake-check accuracy, clarity score
```
