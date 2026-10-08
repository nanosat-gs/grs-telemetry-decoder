"""Portas do decodificador.

Protocols, como no resto da estação: um adapter não herda de nada, só precisa
ter os métodos.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from telemetry_decoder.domain.models import DecodeOutcome, FsatPacket, LinkFrame, RawPacket, TelemetryRecord
from telemetry_decoder.domain.packets.base import Field


class RawPacketSource(Protocol):
    """Os raw packets que ainda não têm linha em decoded_frames para a versão
    atual do decoder.

    "Ainda sem linha", e NÃO "id maior que o último lido". Os dois archivers
    (VHF e UHF) gravam em lotes, cada lote numa transação: um id menor pode
    ficar visível depois de um maior, e um cursor por id pularia esses pacotes
    para sempre. Ver docs/schema-contract.md.
    """

    def pending(self, decoder_version: str, limit: int,
                since_id: int | None = None, radio: str | None = None) -> list[RawPacket]: ...


class LinkDecoder(Protocol):
    """O enlace: dos bytes depois do syncword até o pacote."""

    def decode(self, data: bytes) -> LinkFrame: ...


class PacketDecoder(Protocol):
    """Um tipo de pacote. A implementação comum é `FixedLayoutDecoder`.

    `fields` descreve as colunas da tabela do tipo — é dela que saem o DDL, o
    INSERT, o schema_check e o que a API mostra.
    """

    pkt_id: int
    packet_type: str
    table: str
    fields: tuple[Field, ...]

    def decode(self, packet: FsatPacket) -> TelemetryRecord: ...


class TelemetryRepository(Protocol):
    """Onde o resultado vai. Uma transação por pacote: decoded_frames e a
    tabela do tipo entram juntas ou não entram."""

    def save(self, outcome: DecodeOutcome) -> bool: ...


class TelemetryReader(Protocol):
    """A leitura que a API faz."""

    def latest(self, decoder: PacketDecoder, sat_profile: str, limit: int,
               decoder_version: str | None = None) -> Sequence[dict]: ...
    def stats(self, decoder_version: str) -> dict: ...
