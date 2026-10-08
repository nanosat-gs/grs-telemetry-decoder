"""Extrai de um WAV de discriminador os raw packets NGHam, como o detector os publicaria.

Gerou tests/fixtures/real_frames.json. Fica aqui para que a fixture possa ser
refeita e conferida, não para rodar nos testes — depende do grs-demodulator
(a recuperação de tempo M&M da estação), que este serviço não instala.

    python tools/extract_ngham_slices.py <wav> --baud 1200

O WAV é a saída de áudio de um receptor em FM (gqrx em Narrow FM, ou o que o
spacelab-decoder usa nas amostras dele): o discriminador já foi aplicado, e o
caminho começa na recuperação de tempo — igual ao
grs-station/tests/test_rx_real_signal.py. Cada syncword `5D E6 2A 7E`
achado vira os 255 bytes seguintes, que é exatamente o payload de uma linha
de raw_packets.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct

import numpy as np

SYNC = bytes((0x5D, 0xE6, 0x2A, 0x7E))
SLICE_BYTES = 255


def read_wav(path: pathlib.Path) -> tuple[int, np.ndarray]:
    """PCM 16 bits ou float32 (formato 3, que o módulo `wave` não lê)."""
    blob = path.read_bytes()
    position, fmt, data = 12, None, None
    while position < len(blob):
        chunk, size = blob[position:position + 4], struct.unpack("<I", blob[position + 4:position + 8])[0]
        body = blob[position + 8:position + 8 + size]
        if chunk == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif chunk == b"data":
            data = body
        position += 8 + size + (size & 1)
    tag, channels, rate, _, _, bits = fmt
    samples = np.frombuffer(data, dtype={(1, 16): "<i2", (3, 32): "<f4"}[(tag, bits)]).astype(np.float64)
    if channels > 1:
        samples = samples.reshape(-1, channels)[:, 0]
    if tag == 1:
        samples /= 32768.0
    return rate, samples


def bits_of(data: bytes) -> list[int]:
    return [(byte >> i) & 1 for byte in data for i in range(7, -1, -1)]


def main() -> None:
    from grs_demodulator.timing_sync.mm import MM

    parser = argparse.ArgumentParser()
    parser.add_argument("wav", type=pathlib.Path)
    parser.add_argument("--baud", type=int, required=True)
    args = parser.parse_args()

    rate, audio = read_wav(args.wav)
    mm = MM(samp_rate=rate, baud=args.baud)
    bits: list[int] = []
    # Em blocos de 2 s, com o mesmo objeto MM — o estado atravessa os blocos,
    # como no serviço e no teste do sinal real.
    for start in range(0, len(audio), rate * 2):
        bits.extend(int(b) for b in mm.decode_stream(audio[start:start + rate * 2]))

    sync = bits_of(SYNC)
    slices = []
    index = 0
    while index <= len(bits) - len(sync):
        if bits[index:index + len(sync)] == sync:
            chunk = bits[index + 32:index + 32 + SLICE_BYTES * 8]
            available = len(chunk) // 8
            chunk += [0] * (SLICE_BYTES * 8 - len(chunk))
            payload = bytes(int("".join(map(str, chunk[i:i + 8])), 2) for i in range(0, len(chunk), 8))
            slices.append({"bit_offset": index + 32, "bytes_available": available, "hex": payload.hex()})
            index += len(sync)
        else:
            index += 1

    print(json.dumps({"bits": len(bits), "slices": slices}, indent=2))


if __name__ == "__main__":
    main()
