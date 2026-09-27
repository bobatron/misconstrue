"""One background thread for heavy jobs: speech models are too big to run several at once."""
from concurrent.futures import ThreadPoolExecutor

worker = ThreadPoolExecutor(max_workers=1)
