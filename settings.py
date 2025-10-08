import os
from dataclasses import dataclass

@dataclass
class Settings:
    CSV_PATH: str = os.getenv("CSV_PATH", "sample.csv")
    CSV_SEP: str = os.getenv("CSV_SEP", ",")
    CSV_ENCODING: str = os.getenv("CSV_ENCODING", "utf-8")

settings = Settings()
