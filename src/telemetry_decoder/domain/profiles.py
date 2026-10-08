"""Os perfis de missão: que satélite é, que pacotes manda, e quem decodifica cada um.

É o ÚNICO lugar que muda quando um tipo de pacote novo entra: uma linha no
`decoders` do perfil. O cano (enlace, cabeçalho, banco, API) não sabe que
tipos existem — ele pergunta ao perfil.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from telemetry_decoder.domain.packets import general_telemetry
from telemetry_decoder.domain.ports import PacketDecoder
from telemetry_decoder.domain.satellite_enums import DownlinkId


@dataclass(frozen=True)
class MissionProfile:
    # Vai na coluna `sat_profile` e na URL da API (/api/telemetry/<name>/...).
    name: str
    sat_id: str
    description: str
    callsigns: frozenset[str]
    # Todo ID que o satélite manda, com o nome. Um ID daqui sem decoder vira
    # `not_implemented`; um ID fora daqui, `unknown_packet`.
    packet_types: Mapping[int, str]
    # Por qual rádio cada tipo desce, onde se sabe. Chegar pelo outro é sinal
    # de estação mal configurada (o bug do IP trocado entre detectores, em
    # grs-station/docs/rx-datapath.md), não de pacote ruim.
    expected_radio: Mapping[int, str] = field(default_factory=dict)
    decoders: Mapping[int, PacketDecoder] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for pkt_id, decoder in self.decoders.items():
            if decoder.pkt_id != pkt_id or pkt_id not in self.packet_types:
                raise ValueError(f"{self.name}: decoder registrado no ID errado: {pkt_id:#04x}")
            if decoder.packet_type != self.packet_types[pkt_id]:
                raise ValueError(f"{self.name}: nome do tipo {pkt_id:#04x} diverge")

    def packet_type(self, pkt_id: int) -> str | None:
        return self.packet_types.get(pkt_id)

    def decoder(self, pkt_id: int) -> PacketDecoder | None:
        return self.decoders.get(pkt_id)

    def decoder_by_type(self, packet_type: str) -> PacketDecoder | None:
        return next((d for d in self.decoders.values() if d.packet_type == packet_type), None)

    def radio_mismatch(self, pkt_id: int, radio: str | None) -> bool:
        expected = self.expected_radio.get(pkt_id)
        return expected is not None and radio is not None and radio != expected


FS2 = MissionProfile(
    name="fs2",
    sat_id="golds-ufsc",
    description="FloripaSat-2 / GOLDS-UFSC — OBDH2 + TTC2, NGHam nos dois rádios",
    callsigns=frozenset({"PY0EFS"}),
    packet_types=MappingProxyType({member.value: member.packet_type for member in DownlinkId}),
    expected_radio=MappingProxyType({
        # TTC_0 = UHF (dados, 468,4 MHz); TTC_1 = VHF (beacon, 145,9 MHz). O
        # 0x10 sai pelo TTC_0 (general_telemetry.c) e o spacelab-decoder o
        # põe no downlink_uhf; o ping e o beacon do EPS, no downlink_vhf.
        DownlinkId.EPS_BEACON: "vhf",
        DownlinkId.PING_ANSWER: "vhf",
        DownlinkId.GENERAL_TELEMETRY: "uhf",
        DownlinkId.DATA_REQUEST_ANSWER: "uhf",
    }),
    decoders=MappingProxyType({
        DownlinkId.GENERAL_TELEMETRY: general_telemetry.DECODER,
    }),
)

# O FS-1 só existe em gravação: é corpus de regressão do enlace, não missão.
# Mínimo de propósito — os tipos que as gravações contêm (spacelab-decoder,
# floripasat-1.json), nenhum decoder. Só é usado com --profile fs1.
FS1 = MissionProfile(
    name="fs1",
    sat_id="floripasat-1",
    description="FloripaSat-1 (fora de órbita) — só replay e regressão",
    callsigns=frozenset({"PY0EFS"}),
    packet_types=MappingProxyType({0x00: "obdh_beacon", 0x01: "eps_beacon",
                                   0x02: "ttc_beacon", 0x10: "telemetry"}),
    expected_radio=MappingProxyType({0x00: "vhf", 0x01: "vhf", 0x02: "vhf", 0x10: "uhf"}),
)

PROFILES: Mapping[str, MissionProfile] = MappingProxyType({p.name: p for p in (FS2, FS1)})

# Os perfis que concorrem pelo callsign de um pacote ao vivo. O FS-1 usava o
# mesmo indicativo, mas não transmite mais: deixá-lo aqui faria todo pacote do
# FS-2 ambíguo.
LIVE_PROFILES: tuple[MissionProfile, ...] = (FS2,)


def get_profile(name: str) -> MissionProfile:
    try:
        return PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise ValueError(f"perfil desconhecido {name!r}; conhecidos: {known}") from None


def resolve(callsign: str, forced: MissionProfile | None = None) -> MissionProfile | None:
    """O perfil de um pacote pelo callsign. `forced` (o --profile da linha de
    comando) vale para qualquer callsign: é o reprocessamento de uma gravação
    cujo satélite quem roda já sabe."""
    if forced is not None:
        return forced

    return next((p for p in LIVE_PROFILES if callsign in p.callsigns), None)
