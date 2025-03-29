import os
from pathlib import Path

DEFAULT_DATA_DIR = ".data"

data_dir = Path(os.getenv("DATA_DIR", DEFAULT_DATA_DIR))
