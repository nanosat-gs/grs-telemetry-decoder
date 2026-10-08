"""Fábrica de quadros para os testes: pacote FSat -> NGHam (PyNGHam.encode) -> raw packet.

O raw packet é o que o detector publica: os 255 bytes DEPOIS do syncword —
size tag, codeword, e lixo até completar a fatia. O lixo é de propósito: o
adapter de enlace tem de parar no fim do codeword, e um teste com zeros no
fim não pegaria um adapter que lesse demais.
"""

from __future__ import annotations

import struct
from datetime import datetime, timezone

import pyngham

from telemetry_decoder.domain.models import RawPacket
from telemetry_decoder.domain.packets.general_telemetry import FIELDS

NOW = datetime(2026, 10, 6, 12, 0, 0, 123456, tzinfo=timezone.utc)
# O maior quadro NGHam: 3 de size tag + 255 de codeword. A estação publicava
# 255 e cortava os pacotes de mais de 188 bytes — ver test_link.py.
SLICE = 258
# preâmbulo 4 B + syncword 4 B, que o detector já consumiu
NGHAM_PREFIX = 8

# Um General Telemetry com valor conhecido em todo campo, cobrindo os cantos:
# negativos nos int16, máximos nos uint, e um epoch de verdade.
GENERAL_TELEMETRY_VALUES: dict[str, int] = {field.name: 0 for field in FIELDS}
GENERAL_TELEMETRY_VALUES.update({
    "obdh_timestamp": 1_791_201_600,          # 2026-10-05 12:00:00 UTC
    "obdh_mcu_temp": 298,                     # 24,85 °C
    "obdh_input_current": 45,
    "obdh_input_voltage": 3302,
    "obdh_last_reset_cause": 0x0A,
    "obdh_reset_counter": 7,
    "obdh_last_valid_tc": 0x40,
    "ttc_radio_temp": 301,
    "ttc_last_tc_rssi": 0xFFB5,
    "antenna_temp": 280,
    "antenna_status": 0x8888,
    "eps_mcu_temp": 299,
    "eps_input_current": 120,
    "eps_last_reset_cause": 3,
    "eps_reset_counter": 65535,
    "eps_sp_voltage_my_px": 4800,
    "eps_sp_voltage_mx_pz": 4801,
    "eps_sp_voltage_mz_py": 4802,
    "eps_sp_current_my": 110,
    "eps_sp_current_py": 111,
    "eps_sp_current_mx": 112,
    "eps_sp_current_px": 113,
    "eps_sp_current_mz": 114,
    "eps_sp_current_pz": 115,
    "eps_mppt_1_duty": 55,
    "eps_mppt_2_duty": 56,
    "eps_mppt_3_duty": 100,
    "eps_main_bus_voltage": 5000,
    "eps_battery_voltage": 7400,
    "eps_battery_current": -350,              # descarregando
    "eps_battery_avg_current": -32768,        # mínimo do int16
    "eps_battery_acc_current": 2100,
    "eps_battery_monitor_temp": 293,
    "eps_heater_1_duty": 0,
    "eps_heater_2_duty": 25,
    "obdh_main_edc": 1,
    "obdh_main_payload_state": 1,
    "obdh_sec_payload_state": 0,
    "obdh_data_log_page": 123_456,
    "obdh_sbcd_page": 4_294_967_295,          # máximo do uint32
    "obdh_sensors_read_ts": 1_791_201_590,
    "obdh_position_ts": 1_791_201_500,
    "obdh_latitude": -27,                     # Florianópolis
    "obdh_longitude": -48,
    "obdh_altitude": 525,
    "obdh_last_tle_update_ts": 1_791_100_000,
    "obdh_last_contact_ts": 1_791_190_000,
    "obdh_next_sched_tc_ts": 1_791_210_000,
    "obdh_tc_queue_size": 3,
    "obdh_mode": 2,
})


def fsat(pkt_id: int, data: bytes = b"", callsign: bytes = b" PY0EFS") -> bytes:
    assert len(callsign) == 7
    return bytes([pkt_id]) + callsign + data


def general_telemetry(values: dict[str, int] | None = None, length: int = 111,
                      callsign: bytes = b" PY0EFS") -> bytes:
    values = values or GENERAL_TELEMETRY_VALUES
    packet = bytearray(fsat(0x10, bytes(length - 8), callsign))
    for field in FIELDS:
        if field.end <= length:
            struct.pack_into(">" + field.fmt, packet, field.offset, values[field.name])
    return bytes(packet)


def junk(n: int) -> bytes:
    """Lixo determinístico e que não parece size tag nem zero."""
    return bytes((0x5A + 37 * i) & 0xFF for i in range(n))


def ngham_slice(packet: bytes, total: int = SLICE) -> bytes:
    """O que o detector publicaria para este pacote."""
    encoded = bytes(pyngham.PyNGHam().encode(list(packet))[NGHAM_PREFIX:])
    assert encoded, "PyNGHam recusou o pacote (vazio ou > 220 bytes)"
    return (encoded + junk(total))[:total]


def raw_packet(payload: bytes, *, id: int = 1, radio: str | None = "uhf") -> RawPacket:
    return RawPacket(id=id, received_at=NOW, radio=radio, payload=payload)
