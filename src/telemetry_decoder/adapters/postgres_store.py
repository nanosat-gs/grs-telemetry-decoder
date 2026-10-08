"""Adapter Postgres: lê mission_control.raw_packets, escreve decoded_frames e as tabelas por tipo.

Implementa `RawPacketSource`, `TelemetryRepository` e `TelemetryReader` — as
três falam com o mesmo banco e dividem um engine.

## Donos

- `raw_packets` é do `grs-packet-archiver` (grs-iq-recorder). Este serviço só
  LÊ, e confere no boot as colunas que lê.
- `decoded_frames` e `fs2_<tipo>` são deste serviço: nascem no boot com
  `CREATE TABLE IF NOT EXISTS`, ganham as colunas novas com
  `ADD COLUMN IF NOT EXISTS`, e nunca recebem UPDATE nem DELETE.

As colunas de cada `fs2_<tipo>` saem da tabela de campos do decoder
(`Field.sql_type`). Tipo novo = tabela nova, sem SQL escrito à mão.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from telemetry_decoder.domain.models import DecodeOutcome, RawPacket
from telemetry_decoder.domain.ports import PacketDecoder

logger = logging.getLogger(__name__)

SCHEMA = "mission_control"
RAW_TABLE = "raw_packets"
FRAMES_TABLE = "decoded_frames"

# As colunas de raw_packets que este serviço lê. O schema_check confere.
RAW_COLUMNS_READ: tuple[str, ...] = ("id", "received_at", "radio", "payload")

FRAMES_COLUMNS: dict[str, str] = {
    "id": "BIGSERIAL PRIMARY KEY",
    "raw_packet_id": f"BIGINT NOT NULL REFERENCES {{schema}}.{RAW_TABLE}(id)",
    "decoder_version": "TEXT NOT NULL",
    "radio": "TEXT",
    # Copiado de raw_packets: o relógio da ESTAÇÃO, na chegada ao archiver.
    "received_at": "TIMESTAMP WITH TIME ZONE NOT NULL",
    "status": "TEXT NOT NULL",
    "ngham_error": "TEXT",
    "rs_errors": "INTEGER",
    "frame_length": "INTEGER",
    # O pacote já sem NGHam, guardado mesmo quando não há decoder do tipo:
    # um `not_implemented` já é consultável cru hoje. (O reprocessamento não
    # lê daqui — ele refaz o NGHam a partir de raw_packets.)
    "ngham_payload": "BYTEA",
    "pkt_id": "SMALLINT",
    "pkt_type": "TEXT",
    "callsign": "TEXT",
    "sat_profile": "TEXT",
    "radio_mismatch": "BOOLEAN NOT NULL DEFAULT FALSE",
    "detail": "TEXT",
    "decoded_at": "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()",
}

# O cabeçalho comum de toda tabela de tipo; os campos do decoder vêm depois.
RECORD_HEADER: dict[str, str] = {
    "decoded_frame_id": f"BIGINT PRIMARY KEY REFERENCES {{schema}}.{FRAMES_TABLE}(id)",
    "raw_packet_id": "BIGINT NOT NULL",
    "decoder_version": "TEXT NOT NULL",
    "received_at": "TIMESTAMP WITH TIME ZONE NOT NULL",
    "radio": "TEXT",
    "sat_profile": "TEXT NOT NULL",
    # O relógio do satélite, quando o tipo tem um. Pode estar errado (reset
    # do OBDH): por isso a ordenação é por received_at, não por este.
    "sat_time": "TIMESTAMP WITH TIME ZONE",
    "layout": "TEXT NOT NULL",
}


class RawPacketsMissing(RuntimeError):
    """raw_packets não existe: o archiver nunca subiu contra este banco."""


def record_columns(decoder: PacketDecoder) -> dict[str, str]:
    return {**RECORD_HEADER, **{field.name: field.sql_type for field in decoder.fields}}


class PostgresStore:
    def __init__(self, database_url: str, decoders: Iterable[PacketDecoder],
                 engine: Engine | None = None, schema: str = SCHEMA) -> None:
        if not schema.replace("_", "").isalnum():
            raise ValueError(f"nome de schema inválido: {schema!r}")

        self.schema = schema
        self.decoders: tuple[PacketDecoder, ...] = tuple(decoders)
        # connect_timeout curto, pelo mesmo motivo do archiver: com o banco
        # fora, o padrão da libpq pendura cada tentativa por dezenas de
        # segundos e o serviço fica surdo a SIGTERM.
        self._engine = engine if engine is not None else create_engine(
            database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3}
        )
        self._raw = f"{schema}.{RAW_TABLE}"
        self._frames = f"{schema}.{FRAMES_TABLE}"
        self._insert_frame = text(f"""
            INSERT INTO {self._frames} (
                raw_packet_id, decoder_version, radio, received_at, status, ngham_error,
                rs_errors, frame_length, ngham_payload, pkt_id, pkt_type, callsign,
                sat_profile, radio_mismatch, detail
            ) VALUES (
                :raw_packet_id, :decoder_version, :radio, :received_at, :status, :ngham_error,
                :rs_errors, :frame_length, :ngham_payload, :pkt_id, :pkt_type, :callsign,
                :sat_profile, :radio_mismatch, :detail
            )
            ON CONFLICT (raw_packet_id, decoder_version) DO NOTHING
            RETURNING id
        """)
        self._insert_record = {d.table: self._record_insert(d) for d in self.decoders}

    @property
    def engine(self) -> Engine:
        return self._engine

    # --- schema ------------------------------------------------------------------

    def ensure_schema(self) -> None:
        with self._engine.begin() as connection:
            if not self._table_exists(connection, RAW_TABLE):
                raise RawPacketsMissing(
                    f"{self._raw} não existe. Quem a cria é o grs-packet-archiver, no "
                    "boot dele: suba o caminho de recepção (profile rx, rxsim ou "
                    "rtlsdr) antes do decodificador."
                )
            for statement in self._ddl():
                connection.execute(text(statement))

        logger.info("Tabelas prontas: %s, %s.", self._frames,
                    ", ".join(f"{self.schema}.{d.table}" for d in self.decoders))

    def _ddl(self) -> list[str]:
        statements = [self._create(FRAMES_TABLE, FRAMES_COLUMNS, unique=(
            f"CONSTRAINT {FRAMES_TABLE}_raw_version_key UNIQUE (raw_packet_id, decoder_version)"))]
        statements.append(
            f"CREATE INDEX IF NOT EXISTS {FRAMES_TABLE}_type_idx "
            f"ON {self._frames} (sat_profile, pkt_type, decoder_version, id DESC)"
        )

        for decoder in self.decoders:
            statements.append(self._create(decoder.table, record_columns(decoder)))
            statements += self._add_field_columns(decoder)
            statements.append(
                f"CREATE INDEX IF NOT EXISTS {decoder.table}_received_idx "
                f"ON {self.schema}.{decoder.table} (sat_profile, decoder_version, received_at DESC)"
            )

        return statements

    def _create(self, table: str, columns: dict[str, str], unique: str | None = None) -> str:
        # `{schema}` nas definições: as FKs apontam para o schema DESTA
        # instância, e não para mission_control fixo (os testes usam um
        # schema descartável).
        body = [f"{name} {sql.format(schema=self.schema)}" for name, sql in columns.items()]
        if unique:
            body.append(unique)
        return f"CREATE TABLE IF NOT EXISTS {self.schema}.{table} (\n    " + ",\n    ".join(body) + "\n)"

    def _add_field_columns(self, decoder: PacketDecoder) -> list[str]:
        """Campo novo num decoder vira coluna nova sem migração à mão.

        CREATE TABLE IF NOT EXISTS não mexe numa tabela que já existe; é por
        aqui que um campo acrescentado à tabela de um decoder chega ao banco.
        Só os campos do decoder, que aceitam NULL — as linhas antigas ficam
        NULL nele, que é a verdade: aquele layout não trazia o campo. Mudar o
        TIPO de um campo, ou o cabeçalho comum, não passa por aqui: o
        schema_check acusa, e a migração é decisão de alguém.
        """
        return [
            f"ALTER TABLE {self.schema}.{decoder.table} "
            f"ADD COLUMN IF NOT EXISTS {field.name} {field.sql_type}"
            for field in decoder.fields
        ]

    def _table_exists(self, connection: Connection, table: str) -> bool:
        return connection.execute(
            text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"{self.schema}.{table}"}
        ).scalar()

    # --- RawPacketSource -----------------------------------------------------------

    def pending(self, decoder_version: str, limit: int,
                since_id: int | None = None, radio: str | None = None) -> list[RawPacket]:
        """Anti-join, e não cursor por id — ver RawPacketSource em domain/ports.py."""
        if limit <= 0:
            raise ValueError(f"limit precisa ser positivo, veio {limit}")

        filters = ""
        params: dict = {"version": decoder_version, "limit": limit}
        if since_id is not None:
            filters += " AND r.id >= :since_id"
            params["since_id"] = since_id
        if radio is not None:
            filters += " AND r.radio = :radio"
            params["radio"] = radio

        query = text(f"""
            SELECT r.id, r.received_at, r.radio, r.payload
            FROM {self._raw} r
            WHERE NOT EXISTS (
                SELECT 1 FROM {self._frames} d
                WHERE d.raw_packet_id = r.id AND d.decoder_version = :version
            ){filters}
            ORDER BY r.id
            LIMIT :limit
        """)
        with self._engine.connect() as connection:
            return [RawPacket(id=row.id, received_at=row.received_at, radio=row.radio,
                              payload=bytes(row.payload))
                    for row in connection.execute(query, params)]

    # --- TelemetryRepository -------------------------------------------------------

    def save(self, outcome: DecodeOutcome) -> bool:
        """:return: False se este pacote já tinha linha nesta versão (outro
        processo chegou antes). Nada é gravado pela metade."""
        frame = outcome.frame
        with self._engine.begin() as connection:
            frame_id = connection.execute(self._insert_frame, {
                "raw_packet_id": frame.raw_packet_id,
                "decoder_version": frame.decoder_version,
                "radio": frame.radio,
                "received_at": frame.received_at,
                "status": frame.status.value,
                "ngham_error": frame.ngham_error,
                "rs_errors": frame.rs_errors,
                "frame_length": frame.frame_length,
                "ngham_payload": frame.ngham_payload,
                "pkt_id": frame.pkt_id,
                "pkt_type": frame.pkt_type,
                "callsign": frame.callsign,
                "sat_profile": frame.sat_profile,
                "radio_mismatch": frame.radio_mismatch,
                "detail": frame.detail,
            }).scalar()

            if frame_id is None:
                return False

            if outcome.record is not None:
                record = outcome.record
                connection.execute(self._insert_record[outcome.table], {
                    "decoded_frame_id": frame_id,
                    "raw_packet_id": frame.raw_packet_id,
                    "decoder_version": frame.decoder_version,
                    "received_at": frame.received_at,
                    "radio": frame.radio,
                    "sat_profile": frame.sat_profile,
                    "sat_time": record.sat_time,
                    "layout": record.layout,
                    **record.values,
                })

        return True

    def _record_insert(self, decoder: PacketDecoder):
        names = list(record_columns(decoder))
        return text(
            f"INSERT INTO {self.schema}.{decoder.table} ({', '.join(names)}) "
            f"VALUES ({', '.join(':' + name for name in names)})"
        )

    # --- TelemetryReader -----------------------------------------------------------

    def latest(self, decoder: PacketDecoder, sat_profile: str, limit: int,
               decoder_version: str | None = None) -> Sequence[dict]:
        """Os mais recentes, pelo relógio da ESTAÇÃO.

        `received_at`, e não `sat_time`: o archiver carimba na chegada, então
        um lote gravado com atraso não passa na frente de nada; e o relógio
        do satélite pode voltar para trás num reset do OBDH.
        """
        if limit <= 0:
            raise ValueError(f"limit precisa ser positivo, veio {limit}")

        version_filter = "AND t.decoder_version = :version" if decoder_version else ""
        query = text(f"""
            SELECT t.*, d.callsign, d.rs_errors, d.radio_mismatch, d.pkt_id
            FROM {self.schema}.{decoder.table} t
            JOIN {self._frames} d ON d.id = t.decoded_frame_id
            WHERE t.sat_profile = :profile {version_filter}
            ORDER BY t.received_at DESC, t.raw_packet_id DESC
            LIMIT :limit
        """)
        with self._engine.connect() as connection:
            return [dict(row._mapping) for row in connection.execute(
                query, {"profile": sat_profile, "version": decoder_version, "limit": limit})]

    def stats(self, decoder_version: str) -> dict:
        with self._engine.connect() as connection:
            by_status = {row.status: row.n for row in connection.execute(text(
                f"SELECT status, count(*) AS n FROM {self._frames} "
                "WHERE decoder_version = :v GROUP BY status"), {"v": decoder_version})}
            by_type = [dict(row._mapping) for row in connection.execute(text(f"""
                SELECT sat_profile, pkt_id, pkt_type, radio, status, count(*) AS n,
                       max(received_at) AS last_received_at
                FROM {self._frames} WHERE decoder_version = :v AND pkt_id IS NOT NULL
                GROUP BY sat_profile, pkt_id, pkt_type, radio, status
                ORDER BY sat_profile, pkt_id, radio, status"""), {"v": decoder_version})]
            raw_total = connection.execute(text(f"SELECT count(*) FROM {self._raw}")).scalar()
            pending = connection.execute(text(f"""
                SELECT count(*) FROM {self._raw} r WHERE NOT EXISTS (
                    SELECT 1 FROM {self._frames} d
                    WHERE d.raw_packet_id = r.id AND d.decoder_version = :v)"""),
                {"v": decoder_version}).scalar()
            last = connection.execute(text(
                f"SELECT max(decoded_at) FROM {self._frames} WHERE decoder_version = :v"),
                {"v": decoder_version}).scalar()

        return {
            "decoder_version": decoder_version,
            "raw_packets": raw_total,
            "pending": pending,
            "by_status": by_status,
            "by_type": by_type,
            "last_decoded_at": last,
        }

    def close(self) -> None:
        self._engine.dispose()
