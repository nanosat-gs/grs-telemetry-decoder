"""Adapter de enlace: NGHam pelo PyNGHam (spacelab-ufsc / mgm8, LGPLv3).

Implementa `LinkDecoder`. O PyNGHam faz o trabalho de verdade — size tag com
tolerância de Hamming, descrambler CCSDS, Reed-Solomon, CRC-16. Este adapter
só o alimenta do jeito certo para o que o detector entrega.

## Por que não `PyNGHam.decode()`

O raw packet são 255 bytes a partir do primeiro bit DEPOIS do syncword: o
detector não sabe onde o quadro termina, e publica uma fatia que cabe o maior
(grs-station/docs/rx-datapath.md). Então os 3 primeiros bytes são o size tag,
e o que passa do codeword é lixo — o começo do próximo pacote, ou ruído.

O `decode()` do PyNGHam, quando o size tag não bate, NÃO falha: volta ao
início e tenta os 3 bytes seguintes como size tag, e assim por diante pelo
lixo adentro. Na maioria das vezes isso termina em erro, mas não há garantia
— e um pacote "achado" no meio do lixo seria telemetria inventada com CRC
válido por acaso (1 em 65 536 por tentativa). Aqui o size tag é conferido UMA
vez, nos 3 primeiros bytes, e o codeword é lido com o tamanho que ele diz.

Para isso o adapter olha o estado interno do decodificador
(`_decoder_state`, `_decoder_size_nr`). Por isso o pyproject pina a versão
exata do PyNGHam.
"""

from __future__ import annotations

from pyngham import PyNGHam
from pyngham.pyngham import _PYNGHAM_PL_PAR_SIZES, State

from telemetry_decoder.domain.models import LinkFrame

SIZE_TAG_LENGTH = 3


class PyNghamLinkDecoder:
    """Implementa LinkDecoder. Não é thread-safe: o PyNGHam guarda estado."""

    def __init__(self) -> None:
        # Uma instância só: o construtor monta os sete codificadores RS, e
        # remontá-los a cada pacote custaria mais que decodificar.
        self._ngham = PyNGHam()

    def decode(self, data: bytes) -> LinkFrame:
        ngham = self._ngham
        # Uma chamada anterior pode ter parado no meio de um quadro.
        ngham._decoder_state = State.SIZE_TAG.value

        if len(data) < SIZE_TAG_LENGTH:
            return LinkFrame(payload=None, error="truncated")

        for byte in data[:SIZE_TAG_LENGTH]:
            ngham.decode_byte(byte)

        if ngham._decoder_state != State.SIZE_KNOWN.value:
            ngham._decoder_state = State.SIZE_TAG.value
            return LinkFrame(payload=None, error="size_tag")

        codeword_length = _PYNGHAM_PL_PAR_SIZES[ngham._decoder_size_nr]
        frame_length = SIZE_TAG_LENGTH + codeword_length

        if len(data) < frame_length:
            ngham._decoder_state = State.SIZE_TAG.value
            return LinkFrame(payload=None, error="truncated", frame_length=frame_length)

        payload: list[int] = []
        errors = 0
        for byte in data[SIZE_TAG_LENGTH:frame_length]:
            payload, errors, _ = ngham.decode_byte(byte)

        # O último byte do codeword dispara RS + CRC. Lista vazia = CRC errado.
        if not payload:
            return LinkFrame(payload=None, error="crc", frame_length=frame_length)

        return LinkFrame(payload=bytes(payload), rs_errors=errors, frame_length=frame_length)
