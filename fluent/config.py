import json
from pathlib import Path
from dataclasses import dataclass, asdict, field

CONFIG_PATH = Path.home() / ".fluent" / "config.json"
BACKEND_URL = "http://localhost:8001"  # override with env var FLUENT_BACKEND_URL


@dataclass
class Config:
    native_language: str = "Spanish"
    job_context: str = "Professional"

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> "Config":
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text())
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        return cls()

    def is_valid(self) -> tuple[bool, str]:
        # Token presence is checked separately via keychain
        return True, ""
