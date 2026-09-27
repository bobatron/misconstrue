CONDA ?= $(shell command -v conda 2>/dev/null || echo /opt/homebrew/Caskroom/miniforge/base/bin/conda)
ENV_BIN := $(shell $(CONDA) info --base)/envs/misconstrue/bin
PY := $(ENV_BIN)/python
export PATH := $(ENV_BIN):$(PATH)

.PHONY: setup models test mask dev api web settings env-example bench

setup:  ## create the Python env, download speech models, pull the local LLM
	$(CONDA) env update -f backend/environment.yml --prune
	$(MAKE) models
	cd frontend && npm install

models:
	mfa model download acoustic english_us_arpa
	mfa model download dictionary english_us_arpa
	$(PY) -c "import nltk; [nltk.download(p, quiet=True) for p in ('averaged_perceptron_tagger_eng', 'cmudict')]"
	ollama pull qwen3:8b

test:
	$(PY) -m pytest backend/tests -q

settings:  ## show the settings in use (defaults + .env + environment)
	$(PY) scripts/cli.py settings

env-example:  ## regenerate .env.example after adding or changing a setting
	$(PY) scripts/cli.py settings --example > .env.example

bench:  ## benchmark saved recordings: make bench ARGS="--good --set CROSSFADE_MS=12"
	$(PY) scripts/bench.py run $(ARGS)

mask:  ## make mask TEXT="hello sir"
	$(PY) scripts/cli.py mask "$(TEXT)"

api:
	cd backend && $(PY) -m uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

dev:  ## API on :8000 and web on :5173
	$(MAKE) -j2 api web
