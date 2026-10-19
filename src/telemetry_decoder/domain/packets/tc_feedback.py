"""TC Feedback (0x13): o resultado de um telecomando que não tem resposta própria.

Fonte do layout: `spacelab-ufsc/obdh2`, `firmware/app/tasks/process_tc.c`,
`send_tc_feedback` (tag v1.0, commit 3f0ad36), conferido com
`doc/user_manual/packets.rst`. Sai pelo `TTC_0` (UHF). Offsets contados do
início do pacote — a coluna "Frame" da spec.

Respondem com ele: Enter/Leave Hibernation, Activate/Deactivate Module e
Payload, Erase Memory, Set Parameter, Update TLE e Schedule TC (este duas
vezes: ao entrar na fila e ao executar). Os pares estão em
uplink-pares-e-estados-fs2.md §2.

O feedback não traz os argumentos do TC nem número de sequência: o que casa a
resposta com o telecomando é o indicativo de quem pediu mais o ID do TC.

`error_code` é `int16` no firmware (`satellite.h:152`, `ERRNO_FB_*`):
0 sucesso, -1 timeout do mission manager, -2 falha de comunicação com o
subsistema, -3 com o dispositivo, -4 ao gravar na FRAM, -5 ao agendar o TC.
"""

from __future__ import annotations

from telemetry_decoder.domain.packets.base import Field, FixedLayoutDecoder
from telemetry_decoder.domain.satellite_enums import DownlinkId

FIELDS: tuple[Field, ...] = (
    Field("requester_callsign", 8, "7s", "", "Indicativo de quem mandou o telecomando"),
    Field("tc_id", 15, "B", "", "ID do telecomando a que o feedback responde (UplinkId)"),
    Field("sat_timestamp", 16, "I", "s", "Relógio do satélite na execução"),
    Field("error_code", 20, "h", "", "Resultado: 0 sucesso, negativo = erro (TcFeedbackCode)"),
)

DECODER = FixedLayoutDecoder(
    pkt_id=DownlinkId.TC_FEEDBACK,
    packet_type=DownlinkId.TC_FEEDBACK.packet_type,
    table="fs2_tc_feedback",
    fields=FIELDS,
    layouts={22: "obdh2-22"},
    sat_time_field="sat_timestamp",
    source="obdh2 firmware/app/tasks/process_tc.c, send_tc_feedback (v1.0, 3f0ad36)",
)
