"""O adapter Postgres contra um banco DE VERDADE, num schema descartável.

Criado e apagado pelo próprio teste — nunca as tabelas da estação. Sem
TELEMETRY_TEST_DATABASE_URL o arquivo é pulado. Com a estação de pé:

    TELEMETRY_TEST_DATABASE_URL=postgresql+psycopg2://admin:admin@localhost:5432/tc_generator \\
        python -m pytest -q tests/test_postgres.py

O `raw_packets` daqui é uma cópia mínima do do archiver (grs-iq-recorder,
postgres_packet_archive.py): só as colunas que o decodificador lê. As outras
não fazem diferença para este lado, e o schema_check confere só estas.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text

from frames import NOW, fsat, general_telemetry, junk, ngham_slice
from telemetry_decoder.adapters.postgres_store import PostgresStore, RawPacketsMissing
from telemetry_decoder.adapters.pyngham_link import PyNghamLinkDecoder
from telemetry_decoder.application.decode_loop import decode_pending
from telemetry_decoder.domain.packets.base import Field, FixedLayoutDecoder
from telemetry_decoder.domain.packets.general_telemetry import DECODER, FIELDS
from telemetry_decoder.schema_check import SchemaMismatch, check_schema

DATABASE_URL = os.environ.get("TELEMETRY_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TELEMETRY_TEST_DATABASE_URL não definido")


@pytest.fixture
def engine():
    engine = create_engine(DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def schema(engine):
    name = f"teste_decoder_{uuid.uuid4().hex[:8]}"
    with engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {name}"))
    yield name
    with engine.begin() as connection:
        connection.execute(text(f"DROP SCHEMA {name} CASCADE"))


def create_raw_packets(engine, schema):
    with engine.begin() as connection:
        connection.execute(text(f"""
            CREATE TABLE {schema}.raw_packets (
                id BIGSERIAL PRIMARY KEY,
                received_at TIMESTAMP WITH TIME ZONE NOT NULL,
                payload BYTEA NOT NULL,
                radio TEXT
            )"""))


def insert_raw(connection, schema, payload, radio="uhf", received_at=NOW) -> int:
    return connection.execute(text(
        f"INSERT INTO {schema}.raw_packets (received_at, payload, radio) "
        "VALUES (:t, :p, :r) RETURNING id"), {"t": received_at, "p": payload, "r": radio}).scalar()


@pytest.fixture
def store(engine, schema):
    create_raw_packets(engine, schema)
    store = PostgresStore(DATABASE_URL, [DECODER], engine=engine, schema=schema)
    store.ensure_schema()
    return store


def decode(store, version="v1", **kwargs):
    return decode_pending(store, PyNghamLinkDecoder(), store, decoder_version=version, **kwargs)


# --- schema ---------------------------------------------------------------------


def test_sem_raw_packets_o_boot_explica_o_que_falta(engine, schema):
    store = PostgresStore(DATABASE_URL, [DECODER], engine=engine, schema=schema)

    with pytest.raises(RawPacketsMissing, match="grs-packet-archiver"):
        store.ensure_schema()


def test_schema_nasce_confere_e_e_idempotente(store):
    store.ensure_schema()

    check_schema(store.engine, store.decoders, schema=store.schema)


def test_schema_check_acusa_tipo_trocado(store, engine):
    with engine.begin() as connection:
        connection.execute(text(
            f"ALTER TABLE {store.schema}.fs2_general_telemetry ALTER COLUMN eps_battery_current TYPE INTEGER"))

    with pytest.raises(SchemaMismatch, match="eps_battery_current é integer, o decoder espera smallint"):
        check_schema(store.engine, store.decoders, schema=store.schema)


def test_campo_novo_num_decoder_vira_coluna_no_boot(store, engine):
    """Uma tabela que já existe não ganha coluna pelo CREATE TABLE IF NOT
    EXISTS. Campo acrescentado ao decoder tem de chegar ao banco sozinho."""
    extended = FixedLayoutDecoder(
        pkt_id=DECODER.pkt_id, packet_type=DECODER.packet_type, table=DECODER.table,
        fields=FIELDS + (Field("campo_novo", 111, "B"),), layouts={112: "teste"})
    store2 = PostgresStore(DATABASE_URL, [extended], engine=engine, schema=store.schema)

    store2.ensure_schema()

    check_schema(engine, store2.decoders, schema=store.schema)


# --- pendentes e gravação ------------------------------------------------------


def test_decodifica_grava_e_nao_refaz(store, engine):
    with engine.begin() as connection:
        gt = insert_raw(connection, store.schema, ngham_slice(general_telemetry()))
        insert_raw(connection, store.schema, ngham_slice(fsat(0x13, b"\x47\x00")))
        insert_raw(connection, store.schema, junk(258))

    assert dict(decode(store).by_status) == {"ok": 1, "not_implemented": 1, "ngham_failed": 1}
    assert decode(store).processed == 0

    with engine.connect() as connection:
        row = connection.execute(text(
            f"SELECT * FROM {store.schema}.fs2_general_telemetry")).mappings().one()
        not_implemented = connection.execute(text(
            f"SELECT ngham_payload FROM {store.schema}.decoded_frames WHERE status = 'not_implemented'")).scalar()
    assert row["raw_packet_id"] == gt
    assert (row["eps_battery_current"], row["obdh_latitude"], row["obdh_sbcd_page"]) == (-350, -27, 4_294_967_295)
    assert row["layout"] == "obdh2-111"
    assert bytes(not_implemented) == fsat(0x13, b"\x47\x00")


def test_save_repetido_nao_duplica(store, engine):
    from frames import raw_packet
    from telemetry_decoder.application.decode_packet import decode_packet

    with engine.begin() as connection:
        raw_id = insert_raw(connection, store.schema, ngham_slice(general_telemetry()))
    outcome = decode_packet(raw_packet(ngham_slice(general_telemetry()), id=raw_id),
                            PyNghamLinkDecoder(), "v1")

    assert store.save(outcome) is True
    assert store.save(outcome) is False


def test_commits_cruzados_dos_dois_archivers_nao_perdem_pacote(store, engine):
    """O cenário que matou o cursor por id.

    O archiver UHF abre a transação do lote e reserva os ids; o VHF reserva
    o seguinte e faz commit primeiro; o decoder passa; só depois o UHF faz
    commit. Um cursor "já li até o maior id" pularia o lote do UHF para
    sempre. O anti-join pega os dois.
    """
    gt = ngham_slice(general_telemetry())
    uhf = engine.connect()
    uhf_tx = uhf.begin()
    uhf_ids = [insert_raw(uhf, store.schema, gt, radio="uhf") for _ in range(3)]

    with engine.begin() as vhf:
        vhf_id = insert_raw(vhf, store.schema, gt, radio="vhf")

    assert vhf_id > max(uhf_ids)
    assert decode(store).processed == 1   # só o VHF está visível

    uhf_tx.commit()
    uhf.close()

    assert decode(store).processed == 3   # o lote do UHF, de ids MENORES
    with engine.connect() as connection:
        decoded = {row.raw_packet_id: row.radio_mismatch for row in connection.execute(text(
            f"SELECT raw_packet_id, radio_mismatch FROM {store.schema}.decoded_frames"))}
    assert decoded == {**{i: False for i in uhf_ids}, vhf_id: True}


def test_versao_nova_reprocessa_ao_lado(store, engine):
    with engine.begin() as connection:
        insert_raw(connection, store.schema, ngham_slice(general_telemetry()))
    decode(store, "v1")

    assert decode(store, "v2").processed == 1
    assert len(store.latest(DECODER, "fs2", 10, "v1")) == 1
    assert len(store.latest(DECODER, "fs2", 10, "v2")) == 1
    assert len(store.latest(DECODER, "fs2", 10)) == 2


def test_reprocessamento_filtrado(store, engine):
    with engine.begin() as connection:
        ids = [insert_raw(connection, store.schema, ngham_slice(general_telemetry()), radio=radio)
               for radio in ("uhf", "vhf", "uhf", "uhf")]

    decode(store, since_id=ids[1], radio="uhf")

    with engine.connect() as connection:
        done = {row[0] for row in connection.execute(text(
            f"SELECT raw_packet_id FROM {store.schema}.decoded_frames"))}
    assert done == {ids[2], ids[3]}


# --- leitura ----------------------------------------------------------------------


def test_latest_pelo_relogio_da_estacao(store, engine):
    """Gravado por último não é recebido por último: um lote atrasado entra
    depois, com received_at do passado."""
    late = NOW - timedelta(minutes=5)
    with engine.begin() as connection:
        recent = insert_raw(connection, store.schema, ngham_slice(general_telemetry()), received_at=NOW)
        insert_raw(connection, store.schema, ngham_slice(general_telemetry()), received_at=late)
    decode(store)

    rows = store.latest(DECODER, "fs2", 5, "v1")

    assert rows[0]["raw_packet_id"] == recent
    assert rows[0]["callsign"] == "PY0EFS" and rows[0]["rs_errors"] == 0


def test_stats(store, engine):
    with engine.begin() as connection:
        insert_raw(connection, store.schema, ngham_slice(general_telemetry()))
        insert_raw(connection, store.schema, ngham_slice(general_telemetry()), radio="vhf")
        insert_raw(connection, store.schema, junk(258))
    decode(store)
    with engine.begin() as connection:
        insert_raw(connection, store.schema, junk(258))

    stats = store.stats("v1")

    assert (stats["raw_packets"], stats["pending"]) == (4, 1)
    assert stats["by_status"] == {"ok": 2, "ngham_failed": 1}
    assert {(row["radio"], row["n"]) for row in stats["by_type"]} == {("uhf", 1), ("vhf", 1)}
