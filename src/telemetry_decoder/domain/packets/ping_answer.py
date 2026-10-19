"""Ping Answer (0x02): o pong, resposta ao Ping Request (0x40).

Fonte do layout: `spacelab-ufsc/obdh2`, `firmware/app/tasks/process_tc.c`,
`process_tc_ping_request` (tag v1.0, commit 3f0ad36), conferido com
`doc/user_manual/packets.rst`. Sai pelo `TTC_1` (VHF), o mesmo rádio que ouviu
o ping. Offsets contados do início do pacote — a coluna "Frame" da spec.

O pong só ecoa quem pediu: é por esse indicativo que a estação sabe que a
resposta é ao ping DELA, e não ao de outra estação (ver
uplink-pares-e-estados-fs2.md §4.6).
"""

from __future__ import annotations

from telemetry_decoder.domain.packets.base import Field, FixedLayoutDecoder
from telemetry_decoder.domain.satellite_enums import DownlinkId

FIELDS: tuple[Field, ...] = (
    Field("requester_callsign", 8, "7s", "", "Indicativo da estação que mandou o ping"),
)

DECODER = FixedLayoutDecoder(
    pkt_id=DownlinkId.PING_ANSWER,
    packet_type=DownlinkId.PING_ANSWER.packet_type,
    table="fs2_ping_answer",
    fields=FIELDS,
    layouts={15: "obdh2-15"},
    source="obdh2 firmware/app/tasks/process_tc.c, process_tc_ping_request (v1.0, 3f0ad36)",
)
