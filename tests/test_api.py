"""A API de leitura, com um leitor falso."""

from __future__ import annotations

import pytest

from frames import GENERAL_TELEMETRY_VALUES, NOW
from telemetry_decoder.adapters.api import create_app
from telemetry_decoder.domain.profiles import PROFILES


def row(**overrides):
    base = {
        "decoded_frame_id": 10, "raw_packet_id": 3, "decoder_version": "v1",
        "received_at": NOW, "radio": "uhf", "sat_profile": "fs2", "sat_time": NOW,
        "layout": "obdh2-111", "callsign": "PY0EFS", "rs_errors": 0,
        "radio_mismatch": False, "pkt_id": 0x10, **GENERAL_TELEMETRY_VALUES,
    }
    return {**base, **overrides}


class FakeReader:
    def __init__(self, rows=(), fail=False):
        self.rows = list(rows)
        self.fail = fail
        self.calls = []

    def latest(self, decoder, sat_profile, limit, decoder_version=None):
        self.calls.append((decoder.packet_type, sat_profile, limit, decoder_version))
        if self.fail:
            raise ConnectionError("banco fora")
        return self.rows[:limit]

    def stats(self, decoder_version):
        if self.fail:
            raise ConnectionError("banco fora")
        return {"decoder_version": decoder_version, "pending": 0, "by_status": {"ok": 1},
                "by_type": [{"pkt_type": "general_telemetry", "last_received_at": NOW}],
                "last_decoded_at": NOW}


def client(reader):
    return create_app(reader, PROFILES, "v1").test_client()


def test_health():
    assert client(FakeReader()).get("/api/health").json == {"ok": True, "decoder_version": "v1"}


def test_catalogo_mostra_todos_os_tipos_e_quem_tem_decoder():
    types = {t["packet_type"]: t for t in client(FakeReader()).get("/api/telemetry").json["fs2"]["types"]}

    assert len(types) == 9
    assert types["general_telemetry"]["decoder"] is True
    assert types["general_telemetry"]["expected_radio"] == "uhf"
    assert types["tc_feedback"]["decoder"] is True
    assert types["param_value"]["decoder"] is False


def test_latest_converte_unidades_e_guarda_o_cru():
    reader = FakeReader([row()])

    body = client(reader).get("/api/telemetry/fs2/general_telemetry/latest").json["record"]
    fields = {f["name"]: f for f in body["fields"]}

    assert reader.calls == [("general_telemetry", "fs2", 1, "v1")]
    assert body["received_at"] == NOW.isoformat()
    assert fields["obdh_mcu_temp"]["raw"] == 298
    assert (fields["obdh_mcu_temp"]["value"], fields["obdh_mcu_temp"]["display_unit"]) == (24.85, "°C")
    assert (fields["eps_battery_voltage"]["value"], fields["eps_battery_voltage"]["display_unit"]) == (7.4, "V")
    assert fields["eps_battery_current"]["value"] == -350
    assert fields["obdh_timestamp"]["value"] == "2026-10-05T12:00:00+00:00"


def test_instante_zero_e_nunca():
    body = client(FakeReader([row(obdh_last_contact_ts=0)])).get(
        "/api/telemetry/fs2/general_telemetry/latest").json["record"]

    assert next(f for f in body["fields"] if f["name"] == "obdh_last_contact_ts")["value"] is None


def test_sem_telemetria_ainda():
    response = client(FakeReader()).get("/api/telemetry/fs2/general_telemetry/latest")

    assert response.status_code == 200
    assert response.json == {"record": None}


def test_historico_com_limite():
    reader = FakeReader([row(raw_packet_id=i) for i in range(5)])

    body = client(reader).get("/api/telemetry/fs2/general_telemetry?limit=3").json

    assert [r["raw_packet_id"] for r in body["records"]] == [0, 1, 2]


@pytest.mark.parametrize("url, status", [
    ("/api/telemetry/fs9/general_telemetry/latest", 404),
    ("/api/telemetry/fs2/nao_existe/latest", 404),
    ("/api/telemetry/fs2/param_value/latest", 501),
    ("/api/telemetry/fs2/general_telemetry?limit=0", 400),
    ("/api/telemetry/fs2/general_telemetry?limit=abc", 400),
    ("/api/telemetry/fs2/general_telemetry?limit=5000", 400),
])
def test_erros(url, status):
    assert client(FakeReader()).get(url).status_code == status


def test_banco_fora_e_503():
    response = client(FakeReader(fail=True)).get("/api/telemetry/fs2/general_telemetry/latest")

    assert response.status_code == 503
    assert client(FakeReader(fail=True)).get("/api/decoder/stats").status_code == 503


def test_stats():
    body = client(FakeReader()).get("/api/decoder/stats").json

    assert body["by_status"] == {"ok": 1}
    assert body["last_decoded_at"] == NOW.isoformat()
