from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IrreversibleRule(BaseModel):
    name_patterns: list[str] = Field(default_factory=list)
    path_patterns: list[str] = Field(default_factory=list)
    on_match: str = "escalate"


class Policy(BaseModel):
    policy_id: str
    version: int = 1
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_url_prefixes: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    denied_actions: list[str] = Field(default_factory=list)
    blocked_hosts: list[str] = Field(default_factory=list)
    irreversible_actions: IrreversibleRule = Field(default_factory=IrreversibleRule)
    sensitive_fields: list[str] = Field(default_factory=list)
    max_steps: int = 25
    step_timeout_ms: int = 15000
    idle_timeout_ms: int = 120000
    loop_repeat_limit: int = 3

    @classmethod
    def load(cls, path: str | Path) -> Policy:
        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)

    def host_allowed(self, host: str) -> bool:
        host = host.split(":")[0].lower()
        if host in {h.lower() for h in self.blocked_hosts}:
            return False
        return host in {h.lower() for h in self.allowed_hosts}

    def url_allowed(self, url: str) -> bool:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if not self.host_allowed(parsed.netloc):
            return False
        if self.allowed_url_prefixes:
            return any(url.startswith(prefix) for prefix in self.allowed_url_prefixes)
        return True

    def action_allowed(self, action: str) -> bool:
        if action in self.denied_actions:
            return False
        return action in self.allowed_actions

    def is_irreversible(self, *, name: str = "", url: str = "") -> bool:
        for pat in self.irreversible_actions.name_patterns:
            if name and re.search(pat, name):
                return True
        for pat in self.irreversible_actions.path_patterns:
            if pat and pat in url:
                return True
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    corebank_host: str = "127.0.0.1"
    corebank_port: int = 8787
    operator_port: int = 8788
    catalog_port: int = 8789
