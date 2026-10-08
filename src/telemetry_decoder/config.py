"""Configuração do decodificador, lida do ambiente.

Só o que muda de máquina para máquina. O que descreve o satélite — tipos de
pacote, layouts, rádio de cada tipo — mora em domain/profiles.py e não se
sobrescreve pelo .env: a telemetria não pode depender de qual era o .env no
dia em que foi decodificada.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_POLL_INTERVAL_S = 1.0
DEFAULT_BATCH_SIZE = 200
DEFAULT_API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 5592
# Esperando o raw_packets aparecer (o archiver ainda não subiu).
DEFAULT_SCHEMA_RETRY_S = 10.0


@dataclass(frozen=True)
class DecoderConfig:
    database_url: str | None
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S
    batch_size: int = DEFAULT_BATCH_SIZE
    api_host: str = DEFAULT_API_HOST
    api_port: int = DEFAULT_API_PORT
    schema_retry_s: float = DEFAULT_SCHEMA_RETRY_S


def _number(source: dict[str, str], name: str, default, kind):
    raw = source.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = kind(raw)
    except ValueError:
        raise ValueError(f"{name} precisa ser {kind.__name__}, veio {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} precisa ser positivo, veio {raw!r}")
    return value


def load_config(env: dict[str, str] | None = None) -> DecoderConfig:
    """:param env: None lê os.environ; os testes passam um dicionário."""
    source = dict(os.environ) if env is None else env

    return DecoderConfig(
        database_url=source.get("PG_DATABASE_URL") or None,
        poll_interval_s=_number(source, "DECODER_POLL_INTERVAL_S", DEFAULT_POLL_INTERVAL_S, float),
        batch_size=_number(source, "DECODER_BATCH_SIZE", DEFAULT_BATCH_SIZE, int),
        api_host=source.get("DECODER_API_HOST", DEFAULT_API_HOST),
        api_port=_number(source, "DECODER_API_PORT", DEFAULT_API_PORT, int),
        schema_retry_s=_number(source, "DECODER_SCHEMA_RETRY_S", DEFAULT_SCHEMA_RETRY_S, float),
    )
