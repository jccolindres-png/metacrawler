"""Resolve a client's optional, explicit crawler/classifier provider."""

import re
from pathlib import Path

import yaml


CLIENTS_DIR = Path(__file__).resolve().parents[2] / "clients"


def provider_for(client, component):
    if component not in ("crawler", "classifier") or not re.fullmatch(r"[a-z][a-z0-9_]*", client):
        raise ValueError("invalid client or component")
    config = CLIENTS_DIR / client / "client.yaml"
    if not config.exists():
        return client
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"invalid client configuration: {config}")
    provider = data.get(f"{component}_provider", client)
    if not isinstance(provider, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", provider):
        raise ValueError(f"invalid {component} provider for {client}")
    if not (CLIENTS_DIR / provider).is_dir():
        raise ValueError(f"unknown {component} provider: {provider}")
    return provider
