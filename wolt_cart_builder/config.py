"""Configuration for Wolt cart builder."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # Wolt Market store URL (change to your city/store)
    store_url: str = "https://wolt.com/he/isr/tel-aviv/market/wolt-market-tel-aviv"

    # Browser settings — headless=False so user can see what's happening
    headless: bool = False
    slow_mo: int = 80  # ms between Playwright actions

    # Path to persist login session (avoids re-login every run)
    session_file: Path = field(default_factory=lambda: Path.home() / ".wolt_session.json")

    # Output directory for summary files
    output_dir: Path = field(default_factory=lambda: Path("wolt_output"))

    # Search result limit per item
    max_search_results: int = 15

    # How long to wait for page elements (ms)
    element_timeout: int = 8000

    # Minimum similarity score to consider a product a match (0-1)
    min_relevance_score: float = 0.3

    # Dry run — search and select but don't actually add to cart
    dry_run: bool = False

    @classmethod
    def from_file(cls, path: str | Path) -> "Config":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        obj = cls()
        for key, value in data.items():
            if key in ("session_file", "output_dir"):
                setattr(obj, key, Path(value))
            elif hasattr(obj, key):
                setattr(obj, key, value)
        return obj

    def save(self, path: str | Path) -> None:
        data = {
            "store_url": self.store_url,
            "headless": self.headless,
            "slow_mo": self.slow_mo,
            "session_file": str(self.session_file),
            "output_dir": str(self.output_dir),
            "max_search_results": self.max_search_results,
            "element_timeout": self.element_timeout,
            "min_relevance_score": self.min_relevance_score,
            "dry_run": self.dry_run,
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
