"""General Telemetry (0x10): a tabela de campos contra a spec e contra o firmware."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from frames import GENERAL_TELEMETRY_VALUES, general_telemetry
from telemetry_decoder.domain import fsat_packet
from telemetry_decoder.domain.packets.base import Field, FixedLayoutDecoder, LayoutMismatch
from telemetry_decoder.domain.packets.general_telemetry import DECODER, FIELDS

LAST_THREE = ("obdh_next_sched_tc_ts", "obdh_tc_queue_size", "obdh_mode")


def decode(packet: bytes):
    return DECODER.decode(fsat_packet.parse(packet))


def test_os_campos_cobrem_os_103_bytes_de_dados_sem_buraco():
    """Do byte 8 (fim do cabeçalho) ao 111, cada byte é de exatamente um
    campo. Um offset digitado errado aparece aqui como buraco ou sobreposição."""
    covered = [offset for field in FIELDS for offset in range(field.offset, field.end)]

    assert sorted(covered) == list(range(8, 111))


@pytest.mark.parametrize("name, offset", [
    # Conferidos um a um contra a coluna "Frame" da spec §4.
    ("obdh_timestamp", 8), ("obdh_last_valid_tc", 21), ("ttc_radio_temp", 22),
    ("antenna_status", 28), ("eps_reset_counter", 35), ("eps_mppt_1_duty", 55),
    ("eps_battery_current", 62), ("obdh_main_edc", 72), ("obdh_sbcd_page", 79),
    ("obdh_latitude", 91), ("obdh_last_contact_ts", 101), ("obdh_mode", 110),
])
def test_offsets_da_spec(name, offset):
    assert next(f for f in FIELDS if f.name == name).offset == offset


def test_layout_de_111_bytes_le_todos_os_valores():
    record = decode(general_telemetry())

    assert record.layout == "obdh2-111"
    assert record.values == GENERAL_TELEMETRY_VALUES


def test_corrente_da_bateria_e_posicao_tem_sinal():
    record = decode(general_telemetry())

    assert record.values["eps_battery_current"] == -350
    assert record.values["eps_battery_avg_current"] == -32768
    assert (record.values["obdh_latitude"], record.values["obdh_longitude"]) == (-27, -48)


def test_big_endian_no_hexdump():
    packet = general_telemetry()

    assert packet[60:62] == (7400).to_bytes(2, "big")    # eps_battery_voltage
    assert packet[8:12] == (1_791_201_600).to_bytes(4, "big")
    assert packet[110] == 2                               # obdh_mode


def test_relogio_do_satelite():
    record = decode(general_telemetry())

    assert record.sat_time == datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def test_layout_antigo_de_105_bytes_deixa_os_tres_ultimos_nulos():
    """O que o spacelab-decoder descreve. Não sabemos qual firmware voa."""
    record = decode(general_telemetry(length=105))

    assert record.layout == "obdh2-105"
    assert all(record.values[name] is None for name in LAST_THREE)
    assert record.values["obdh_last_contact_ts"] == GENERAL_TELEMETRY_VALUES["obdh_last_contact_ts"]


@pytest.mark.parametrize("length", [104, 106, 110, 112])
def test_comprimento_desconhecido_e_layout_mismatch(length):
    with pytest.raises(LayoutMismatch, match=f"{length} bytes"):
        decode(general_telemetry(length=111)[:length] if length < 111
               else general_telemetry() + bytes(length - 111))


@pytest.mark.parametrize("fields, error", [
    ((Field("a", 8, "H"), Field("b", 9, "B")), "sobrepõe"),
    ((Field("a", 8, "H"), Field("a", 10, "B")), "repetido"),
    ((Field("Campo", 8, "H"),), "nome de campo"),
    ((Field("a", 8, "f"),), "formato"),
    ((Field("a", 20, "I"),), "maior layout"),
])
def test_tabela_de_campos_errada_falha_no_import(fields, error):
    with pytest.raises(ValueError, match=error):
        FixedLayoutDecoder(pkt_id=0x77, packet_type="x", table="fs2_x", fields=fields,
                           layouts={16: "teste"})
