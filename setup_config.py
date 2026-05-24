"""
Interactive first-run config setup.
Run once: python setup_config.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from fluent.config import Config

print("=== Fluent — first-run setup ===\n")

cfg = Config.load()

cfg.native_language = input(f"Your native language [{cfg.native_language}]: ").strip() or cfg.native_language
cfg.job_context = input(f"Your job context [{cfg.job_context}]: ").strip() or cfg.job_context
cfg.whisper_api_key = input("OpenAI API key (for Whisper): ").strip() or cfg.whisper_api_key
cfg.claude_api_key = input("Anthropic API key (for Claude): ").strip() or cfg.claude_api_key

cfg.save()
print(f"\nConfig saved to ~/.fluent/config.json")

valid, msg = cfg.is_valid()
if valid:
    print("All API keys present. You're ready to run: python app.py")
else:
    print(f"Warning: {msg}")
