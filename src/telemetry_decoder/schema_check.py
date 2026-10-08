"""Confere, no boot, se o banco tem o que este serviço lê e escreve.

Mesma disciplina do TC Scheduler e do grs-iq-recorder, com uma diferença de
atitude: aqui a divergência DERRUBA o boot. O gravador loga e segue porque a
captura é o artefato e o índice é conveniência. Aqui a telemetria É o
artefato — subir escrevendo numa coluna que sumiu daria um erro por pacote,
para sempre, longe de quem pode consertar. Melhor o `docker compose up`
mostrar a lista de colunas na hora.

Confere:

- de `raw_packets` (do archiver), só as colunas que este serviço LÊ;
- de `decoded_frames` e de cada `fs2_<tipo>`, todas — nome e, nos campos dos
  decoders, o tipo. Um campo que mudou de uint16 para int16 no decoder muda
  de INTEGER para SMALLINT, e o ADD COLUMN do boot não conserta isso.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from telemetry_decoder.adapters.postgres_store import (
    FRAMES_COLUMNS,
    FRAMES_TABLE,
    RAW_COLUMNS_READ,
    RAW_TABLE,
    RECORD_HEADER,
    SCHEMA,
)
from telemetry_decoder.domain.ports import PacketDecoder

logger = logging.getLogger(__name__)

QUERY = text(
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_schema = :schema AND table_name = :table"
)


class SchemaMismatch(RuntimeError):
    pass


def check_schema(engine: Engine, decoders: tuple[PacketDecoder, ...], schema: str = SCHEMA) -> None:
    """Levanta SchemaMismatch com TODOS os problemas de uma vez."""
    expected: dict[str, dict[str, str | None]] = {
        RAW_TABLE: {name: None for name in RAW_COLUMNS_READ},
        FRAMES_TABLE: {name: None for name in FRAMES_COLUMNS},
    }
    for decoder in decoders:
        expected[decoder.table] = {
            **{name: None for name in RECORD_HEADER},
            **{field.name: field.sql_type.lower() for field in decoder.fields},
        }

    problems: list[str] = []
    with engine.connect() as connection:
        for table, columns in expected.items():
            found = {row.column_name: row.data_type for row in connection.execute(
                QUERY, {"schema": schema, "table": table})}
            if not found:
                problems.append(f"{schema}.{table} não existe")
                continue
            for name, data_type in columns.items():
                if name not in found:
                    problems.append(f"{schema}.{table}.{name} não existe")
                elif data_type is not None and found[name] != data_type:
                    problems.append(f"{schema}.{table}.{name} é {found[name]}, o decoder espera {data_type}")

    if problems:
        raise SchemaMismatch("Banco divergente do decodificador:\n  - " + "\n  - ".join(problems))

    logger.info("Schema confere: %d tabelas.", len(expected))
