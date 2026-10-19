"""Value objects do decodificador.

O caminho de um pacote, e o objeto de cada etapa:

    RawPacket      uma linha de mission_control.raw_packets (255 bytes depois do syncword)
    LinkFrame      o que o NGHam devolveu: o pacote, ou por que não deu
    FsatPacket     o cabeçalho comum a todo pacote do satélite: ID + callsign + dados
    TelemetryRecord  os campos de UM tipo de pacote, já como inteiros
    DecodedFrame   a linha de decoded_frames — existe para TODO raw packet, deu certo ou não
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class FrameStatus(str, Enum):
    """O destino de cada raw packet. Toda linha de raw_packets termina em um
    destes — nenhum pacote some sem dizer por quê."""

    OK = "ok"
    # O NGHam recusou: size tag que não bate, quadro cortado, CRC errado.
    NGHAM_FAILED = "ngham_failed"
    # Passou no NGHam, mas é curto demais para o cabeçalho FSat (8 bytes).
    MALFORMED = "malformed"
    # Callsign que nenhum perfil reconhece: outro satélite no mesmo enlace.
    UNKNOWN_SATELLITE = "unknown_satellite"
    # Satélite nosso, ID que o perfil não conhece.
    UNKNOWN_PACKET = "unknown_packet"
    # ID conhecido, ainda sem decoder. O payload fica guardado, e o pacote é
    # decodificado no reprocessamento depois que o decoder do tipo existir.
    NOT_IMPLEMENTED = "not_implemented"
    # Decoder existe, mas o comprimento não é nenhum dos layouts conhecidos.
    LAYOUT_MISMATCH = "layout_mismatch"
    # Exceção dentro de um decoder: bug nosso. Fica registrado e o laço segue —
    # um pacote não pode parar a decodificação de todos os outros.
    DECODER_ERROR = "decoder_error"


@dataclass(frozen=True)
class RawPacket:
    """O que o decoder lê de raw_packets. Só as colunas que ele usa."""

    id: int
    received_at: datetime
    radio: str | None
    payload: bytes


@dataclass(frozen=True)
class LinkFrame:
    """Resultado do enlace (NGHam).

    `rs_errors`: símbolos corrigidos pelo Reed-Solomon. -1 quando o RS não
    conseguiu validar o codeword MAS o CRC passou — o pacote é aceito, porque
    quem protege os dados é o CRC. Acontece nos quadros reais do FS-1, cuja
    paridade não bate com a do PyNGHam (ver tests/test_real_signals.py). Num
    quadro do FS-2 seria um sinal a investigar.
    """

    payload: bytes | None
    rs_errors: int | None = None
    # "size_tag" | "truncated" | "crc"
    error: str | None = None
    # Bytes do raw packet que o quadro ocupou: size tag + codeword.
    frame_length: int | None = None

    @property
    def ok(self) -> bool:
        return self.payload is not None


@dataclass(frozen=True)
class FsatPacket:
    """Cabeçalho comum a todo pacote, de downlink e de uplink (spec §2)."""

    pkt_id: int
    callsign: str
    # O pacote inteiro, cabeçalho incluído: os offsets dos decoders são
    # contados daqui, como na tabela "Frame" da spec §4.
    raw: bytes

    @property
    def length(self) -> int:
        return len(self.raw)


@dataclass(frozen=True)
class TelemetryRecord:
    """Os campos de um tipo de pacote, como inteiros (indicativos como texto)
    — sem conversão de unidade, que fica para a leitura."""

    packet_type: str
    layout: str
    sat_time: datetime | None
    # None = campo que este layout não traz (o 0x10 de 105 bytes não tem os
    # três últimos campos do de 111).
    values: dict[str, int | str | None]


@dataclass(frozen=True)
class DecodedFrame:
    """Uma linha de decoded_frames."""

    raw_packet_id: int
    decoder_version: str
    radio: str | None
    received_at: datetime
    status: FrameStatus
    rs_errors: int | None = None
    ngham_error: str | None = None
    frame_length: int | None = None
    ngham_payload: bytes | None = None
    pkt_id: int | None = None
    pkt_type: str | None = None
    callsign: str | None = None
    sat_profile: str | None = None
    # Tipo que chegou por um rádio diferente do esperado. Decodifica do mesmo
    # jeito: é um aviso sobre a estação, não sobre o pacote.
    radio_mismatch: bool = False
    detail: str | None = None


@dataclass(frozen=True)
class DecodeOutcome:
    frame: DecodedFrame
    record: TelemetryRecord | None = None
    # A tabela onde `record` vai, vinda do decoder do tipo.
    table: str | None = None
