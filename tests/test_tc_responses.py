"""Respostas a telecomando: Ping Answer (0x02) e TC Feedback (0x13).

Os pacotes são montados à mão, campo a campo, como o `process_tc.c` do OBDH2
(v1.0) os monta — e não pela tabela de campos do decoder, senão um offset
errado nos dois lados passaria.
"""

from __future__ import annotations

import struct
from datetime import datetime, timezone

import pytest

from frames import fsat, ngham_slice, raw_packet
from telemetry_decoder.adapters.pyngham_link import PyNghamLinkDecoder
from telemetry_decoder.application.decode_packet import decode_packet
from telemetry_decoder.domain import fsat_packet
from telemetry_decoder.domain.models import FrameStatus
from telemetry_decoder.domain.packets import ping_answer, tc_feedback
from telemetry_decoder.domain.packets.base import LayoutMismatch
from telemetry_decoder.domain.satellite_enums import TcFeedbackCode, UplinkId

STATION = b" PY0SIM"   # 7 bytes com espaço à esquerda, como o SLP manda


def pong(requester: bytes = STATION) -> bytes:
    """process_tc_ping_request: ID, callsign do satélite, os 7 bytes de quem pediu."""
    return fsat(0x02, requester)


def feedback(tc_id: int, error_code: int, timestamp: int, requester: bytes = STATION) -> bytes:
    """send_tc_feedback: quem pediu (7), ID do TC (1), relógio (4), erro int16 (2)."""
    return fsat(0x13, requester + struct.pack(">BIh", tc_id, timestamp, error_code))


def decode(decoder, packet: bytes):
    return decoder.decode(fsat_packet.parse(packet))


# --- Ping Answer ---------------------------------------------------------------


def test_pong_tem_15_bytes_e_ecoa_quem_pediu():
    record = decode(ping_answer.DECODER, pong())

    assert len(pong()) == 15
    assert record.layout == "obdh2-15"
    assert record.values == {"requester_callsign": "PY0SIM"}
    assert record.sat_time is None


def test_pong_de_outra_estacao_traz_o_indicativo_dela():
    assert decode(ping_answer.DECODER, pong(b"PP5ABCD")).values["requester_callsign"] == "PP5ABCD"


# --- TC Feedback ---------------------------------------------------------------


def test_feedback_cobre_os_14_bytes_de_dados_sem_buraco():
    covered = [o for field in tc_feedback.FIELDS for o in range(field.offset, field.end)]

    assert sorted(covered) == list(range(8, 22))


@pytest.mark.parametrize("name, offset", [
    ("requester_callsign", 8), ("tc_id", 15), ("sat_timestamp", 16), ("error_code", 20),
])
def test_offsets_do_send_tc_feedback(name, offset):
    assert next(f for f in tc_feedback.FIELDS if f.name == name).offset == offset


def test_feedback_de_sucesso():
    packet = feedback(UplinkId.ACTIVATE_MODULE, TcFeedbackCode.SUCCESS, 1_791_201_600)

    record = decode(tc_feedback.DECODER, packet)

    assert len(packet) == 22
    assert record.layout == "obdh2-22"
    assert record.values == {
        "requester_callsign": "PY0SIM",
        "tc_id": 0x45,
        "sat_timestamp": 1_791_201_600,
        "error_code": 0,
    }
    assert record.sat_time == datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def test_codigo_de_erro_tem_sinal():
    record = decode(tc_feedback.DECODER, feedback(0x45, TcFeedbackCode.SUBSYSTEM_COMM_FAILURE, 1))

    assert record.values["error_code"] == -2


def test_feedback_curto_nao_e_layout_conhecido():
    with pytest.raises(LayoutMismatch):
        decode(tc_feedback.DECODER, feedback(0x45, 0, 1)[:21])


# --- pelo cano inteiro: NGHam -> cabeçalho -> perfil -> decoder -------------------


@pytest.mark.parametrize("packet, table, radio", [
    (pong(), "fs2_ping_answer", "vhf"),
    (feedback(0x46, 0, 1_791_201_600), "fs2_tc_feedback", "uhf"),
])
def test_respostas_viram_telemetria_no_cano(packet, table, radio):
    outcome = decode_packet(raw_packet(ngham_slice(packet), radio=radio),
                           PyNghamLinkDecoder(), "v1")

    assert outcome.frame.status is FrameStatus.OK
    assert outcome.table == table
    assert outcome.frame.radio_mismatch is False
    assert outcome.frame.ngham_payload == packet
