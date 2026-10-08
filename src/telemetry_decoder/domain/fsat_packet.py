"""O cabeçalho comum a todo pacote do satélite (spec §2, `fsat_pkt.h` do OBDH2).

    [ID 1 B][callsign 7 B][dados]

É a camada que o documento original da fatia chamava de "spacelink": no
`spacelab-decoder` ela aparece como `protocol_network: "SLP"`. Não há mais
nada entre o NGHam e o pacote — só este cabeçalho.
"""

from __future__ import annotations

from telemetry_decoder.domain.models import FsatPacket

HEADER_LENGTH = 8
CALLSIGN_LENGTH = 7


def normalize_callsign(raw: bytes) -> str:
    """Tira o preenchimento do indicativo.

    O FS-2 completa os 7 bytes com espaço à esquerda (`" PY0EFS"`,
    `FSAT_PKT_CALLSIGN_PADDING_CHAR`). O FS-1 completava com '0'
    (`"0PY0EFS"`), e é o que o `_decode_callsign` do spacelab-decoder
    desfaz. Nenhum indicativo nosso começa por zero, então tirar os dois é
    seguro.
    """
    return raw.decode("latin-1").strip(" \x00").lstrip("0")


def parse(data: bytes) -> FsatPacket | None:
    """:return: o pacote, ou None se não couber nem o cabeçalho."""
    if len(data) < HEADER_LENGTH:
        return None

    return FsatPacket(
        pkt_id=data[0],
        callsign=normalize_callsign(data[1 : 1 + CALLSIGN_LENGTH]),
        raw=bytes(data),
    )
