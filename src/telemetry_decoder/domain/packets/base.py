"""O decoder de layout fixo: um pacote descrito por uma tabela de campos.

A maior parte dos pacotes do satélite é isto — offsets fixos, inteiros
big-endian. Descrever o pacote como DADO, e não como código de parse, é o que
deixa o resto do serviço derivar tudo da mesma tabela: as colunas do banco, o
INSERT, o schema_check e o que a API mostra. Um tipo de layout variável (o
Data Request Answer, que muda com o `data_id`) implementa a porta
`PacketDecoder` direto, sem esta classe.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from telemetry_decoder.domain.models import FsatPacket, TelemetryRecord

# Formatos aceitos (módulo struct, sempre big-endian — spec §2) e o que cada
# um vira no Postgres. Fica aqui, e não no adapter, porque a faixa de valores
# é propriedade do campo: um uint16 não cabe em SMALLINT.
SQL_TYPES: Mapping[str, str] = {
    "B": "SMALLINT",    # uint8
    "b": "SMALLINT",    # int8
    "H": "INTEGER",     # uint16
    "h": "SMALLINT",    # int16
    "I": "BIGINT",      # uint32
    "i": "INTEGER",     # int32
}

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class LayoutMismatch(ValueError):
    """Comprimento que não é nenhum dos layouts conhecidos do tipo."""


@dataclass(frozen=True)
class Field:
    name: str
    # Contado do início do pacote, cabeçalho incluído: a coluna "Frame" da
    # spec §4, e não a "PL". Assim o offset aqui é o mesmo do hexdump.
    offset: int
    fmt: str
    unit: str = ""
    description: str = ""

    @property
    def size(self) -> int:
        return struct.calcsize(">" + self.fmt)

    @property
    def end(self) -> int:
        return self.offset + self.size

    @property
    def sql_type(self) -> str:
        return SQL_TYPES[self.fmt]

    def read(self, raw: bytes) -> int:
        return struct.unpack_from(">" + self.fmt, raw, self.offset)[0]


@dataclass(frozen=True)
class FixedLayoutDecoder:
    pkt_id: int
    packet_type: str
    table: str
    fields: tuple[Field, ...]
    # Comprimento total do pacote -> nome do layout. Cada layout é um prefixo
    # do maior: um campo que passa do fim do pacote fica None.
    layouts: Mapping[int, str]
    # Campo com o relógio do satélite (Unix epoch, s), se o tipo tiver um.
    sat_time_field: str | None = None
    # De onde a tabela de campos veio. Vai para a documentação e para o log.
    source: str = ""

    def __post_init__(self) -> None:
        # Erro de digitação numa tabela de 50 campos não aparece em review.
        # Aqui ele derruba o import, antes de qualquer pacote ser gravado errado.
        names = [field.name for field in self.fields]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.packet_type}: campo repetido")
        for field in self.fields:
            if not _IDENTIFIER.match(field.name):
                raise ValueError(f"{self.packet_type}: nome de campo inválido {field.name!r}")
            if field.fmt not in SQL_TYPES:
                raise ValueError(f"{self.packet_type}.{field.name}: formato {field.fmt!r}")
        ordered = sorted(self.fields, key=lambda field: field.offset)
        for previous, current in zip(ordered, ordered[1:]):
            if current.offset < previous.end:
                raise ValueError(f"{self.packet_type}: {current.name} sobrepõe {previous.name}")
        if ordered and ordered[-1].end > max(self.layouts):
            raise ValueError(f"{self.packet_type}: {ordered[-1].name} passa do maior layout")
        if self.sat_time_field is not None and self.sat_time_field not in names:
            raise ValueError(f"{self.packet_type}: sat_time_field {self.sat_time_field!r}")

    def decode(self, packet: FsatPacket) -> TelemetryRecord:
        layout = self.layouts.get(packet.length)
        if layout is None:
            known = ", ".join(str(length) for length in sorted(self.layouts))
            raise LayoutMismatch(
                f"{self.packet_type} com {packet.length} bytes; layouts conhecidos: {known}"
            )

        values = {
            field.name: field.read(packet.raw) if field.end <= packet.length else None
            for field in self.fields
        }

        sat_time = None
        if self.sat_time_field is not None and values[self.sat_time_field] is not None:
            sat_time = datetime.fromtimestamp(values[self.sat_time_field], tz=timezone.utc)

        return TelemetryRecord(
            packet_type=self.packet_type, layout=layout, sat_time=sat_time, values=values
        )
