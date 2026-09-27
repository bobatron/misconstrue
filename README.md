# misconstrue

A fun app: User 1 types a sentence. The app writes a different, innocent-looking
**masked sentence** and gives User 1 a share link. User 2 opens the link and records
themselves reading the masked sentence. The app then chops the recording up at the
phoneme level and plays back a video of User 2 "saying" User 1's original sentence.

## Status
Early development — see the phases below.

- [ ] Phase 0 — repo + environment setup
- [ ] Phase 1 — CLI risk spike: phonetics, masking, alignment, splicing
- [ ] Phase 2 — local LLM (Ollama) masking
- [ ] Phase 3 — web app (FastAPI + React) with retake detection
- [ ] Phase 4 — polish
- [ ] Phase 5 — hosting

## Stack
- Backend: Python 3.11, FastAPI, SQLite, ffmpeg, Montreal Forced Aligner, faster-whisper
- Masking: CMUdict phonetics + a local LLM via [Ollama](https://ollama.com) (free, runs on your machine)
- Frontend: React + Vite + TypeScript, browser `MediaRecorder`
