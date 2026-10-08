"""Configuration loading from config.toml and .env.

Personal files live outside the repository in the user config directory
(~/.config/sidecar by default, or $SIDECAR_CONFIG_DIR): .env with API keys and
config.toml with settings. A config.toml or .env in the repository root is used
only when the user config directory has none.
"""

import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_CONFIG_DIR = Path(os.environ.get("SIDECAR_CONFIG_DIR", "~/.config/sidecar")).expanduser()
DEFAULT_RECORDINGS = "~/Documents/Sidecar/recordings"


@dataclass(frozen=True)
class AudioConfig:
    input_device: str = ""
    sample_rate: int = 16000
    block_frames: int = 1600


@dataclass(frozen=True)
class DeepgramConfig:
    model: str = "nova-3"
    language: str = "en-US"
    utterance_end_ms: int = 1500
    endpointing_ms: int = 300
    keyterms: list[str] = field(default_factory=list)
    mip_opt_out: bool = True


@dataclass(frozen=True)
class CoachConfig:
    live_model: str = "claude-sonnet-5-5"
    mark_model: str = "claude-sonnet-5-5"
    ask_model: str = "claude-sonnet-5-5"
    live_max_tokens: int = 900
    mark_max_tokens: int = 2000
    ask_max_tokens: int = 1000
    live_effort: str = "low"
    mark_effort: str = "medium"
    ask_effort: str = "low"
    live_thinking: str = "between_tools"
    mark_thinking: str = "adaptive"
    ask_thinking: str = "between_tools"
    live_activity: str = "balanced"
    min_interval_s: float = 6
    timer_interval_s: float = 25
    them_trigger_words: int = 12
    timeout_s: float = 15
    mark_timeout_s: float = 40
    chunk_seconds: float = 120
    debug_prompts: bool = False


@dataclass(frozen=True)
class Prices:
    input: float = 2.00
    output: float = 10.00
    cache_read: float = 0.20
    cache_write: float = 2.50


@dataclass(frozen=True)
class SessionConfig:
    default_planned_minutes: int = 30
    interviews_dir: str = DEFAULT_RECORDINGS
    interviewer_label: str = "INTERVIEWER"
    brief_path: str = "examples/research_brief.md"
    prompts_dir: str = "prompts"


@dataclass(frozen=True)
class ServerConfig:
    port: int = 8765


@dataclass(frozen=True)
class Config:
    audio: AudioConfig
    deepgram: DeepgramConfig
    coach: CoachConfig
    prices: Prices
    session: SessionConfig
    server: ServerConfig
    root: Path
    anthropic_api_key: str
    deepgram_api_key: str

    def snapshot(self) -> dict:
        """Return the config as a dict without API keys."""
        return {
            "audio": asdict(self.audio),
            "deepgram": asdict(self.deepgram),
            "coach": asdict(self.coach),
            "prices_per_mtok": asdict(self.prices),
            "session": asdict(self.session),
            "server": asdict(self.server),
        }

    @property
    def interviews_dir(self) -> Path:
        return self.root / Path(self.session.interviews_dir).expanduser()

    @property
    def prompts_dir(self) -> Path:
        return self.root / Path(self.session.prompts_dir).expanduser()

    @property
    def brief_path(self) -> Path:
        return self.root / Path(self.session.brief_path).expanduser()


def default_config_path(root: Path = PROJECT_ROOT) -> Path:
    """The user's config.toml, falling back to one in the repository root."""
    user = USER_CONFIG_DIR / "config.toml"
    return user if user.exists() else root / "config.toml"


def load_config(root: Path = PROJECT_ROOT, config_path: Path | None = None) -> Config:
    """Load settings from a TOML file and API keys from .env files.

    Keys already set in the environment win, then the user .env, then a .env
    in the repository root.
    """
    load_dotenv(USER_CONFIG_DIR / ".env")
    load_dotenv(root / ".env")
    path = config_path if config_path is not None else default_config_path(root)
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    return Config(
        audio=AudioConfig(**data.get("audio", {})),
        deepgram=DeepgramConfig(**data.get("deepgram", {})),
        coach=CoachConfig(**data.get("coach", {})),
        prices=Prices(**data.get("prices_per_mtok", {})),
        session=SessionConfig(**data.get("session", {})),
        server=ServerConfig(**data.get("server", {})),
        root=root,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        deepgram_api_key=os.environ.get("DEEPGRAM_API_KEY", ""),
    )
