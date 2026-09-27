"""App-wide settings. Override any value with an environment variable of the same name."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))

# Masking
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # "ollama" | "none"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
LLM_CANDIDATES = int(os.getenv("LLM_CANDIDATES", "6"))
MIN_CARRIER_ZIPF = float(os.getenv("MIN_CARRIER_ZIPF", "3.5"))  # word frequency floor

# Speech
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small.en")
MFA_ACOUSTIC_MODEL = os.getenv("MFA_ACOUSTIC_MODEL", "english_us_arpa")
MFA_DICTIONARY = os.getenv("MFA_DICTIONARY", "english_us_arpa")
MFA_ROOT_DIR = Path(os.getenv("MFA_ROOT_DIR", Path.home() / "Documents" / "MFA"))
# The pronunciation dictionary we plan with must be the one the aligner uses.
PRONUNCIATION_DICT = Path(
    os.getenv("PRONUNCIATION_DICT", MFA_ROOT_DIR / "pretrained_models" / "dictionary" / f"{MFA_DICTIONARY}.dict")
)
MIN_VARIANT_PROB = 0.3  # pronunciation variants likelier than this must all contain a carrier's sounds

# Completeness gate
MAX_WER = float(os.getenv("MAX_WER", "0.5"))
MIN_CRITICAL_PHONE_MS = float(os.getenv("MIN_CRITICAL_PHONE_MS", "35"))
MAX_WORD_TIME_DRIFT_S = float(os.getenv("MAX_WORD_TIME_DRIFT_S", "0.6"))
MAX_RETAKES = int(os.getenv("MAX_RETAKES", "5"))

# Editing
FPS = 30
OUTPUT_HEIGHT = 480
AUDIO_SR = 48000
CROSSFADE_MS = 8
SNAP_WINDOW_MS = 15
