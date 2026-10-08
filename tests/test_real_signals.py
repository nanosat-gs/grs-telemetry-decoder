"""O enlace contra quadros que vieram DO AR, e contra uma decodificação independente.

Os sintéticos de tests/frames.py saem do PyNGHam.encode() e voltam pelo
PyNGHam.decode(): se os dois concordarem num erro, o teste fica verde. Foi
assim que o syncword invertido passou pela fatia RX (grs-station,
tests/fixtures/README.md). Estes testes não têm essa fraqueza:

- **FS-1, do ar** (DK3WN, 2019): dois quadros NGHam. O primeiro é conferido
  contra o `beacon.csv` que o decoder OFICIAL do SpaceLab produziu da mesma
  passagem — ordem de bit, size tag, descrambler e CRC provados por fora.
- **GOLDS-UFSC (FS-2)**: um beacon real, da amostra do spacelab-decoder. É o
  único quadro do FS-2 que temos, e prova que o Reed-Solomon do PyNGHam é o
  mesmo do satélite (0 correções, sem o -1 do FS-1).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from frames import raw_packet
from telemetry_decoder.adapters.pyngham_link import PyNghamLinkDecoder
from telemetry_decoder.application.decode_packet import decode_packet
from telemetry_decoder.domain.models import FrameStatus
from telemetry_decoder.domain.profiles import FS1

FIXTURES = json.loads((pathlib.Path(__file__).parent / "fixtures" / "real_frames.json").read_text())
FS1_DATA = FIXTURES["fs1_beacon"]
GOLDS = FIXTURES["golds_ufsc_beacon"]

LINK = PyNghamLinkDecoder()


def slice_of(entry: dict) -> bytes:
    return bytes.fromhex(entry["hex"])


# --- FS-1 -------------------------------------------------------------------------


@pytest.mark.parametrize("entry", FS1_DATA["ngham"], ids=lambda e: f"bit{e['bit_offset']}")
def test_fs1_quadros_reais_passam_no_crc(entry):
    frame = LINK.decode(slice_of(entry))

    assert frame.payload is not None
    assert len(frame.payload) == 39
    assert frame.payload[1:8] == b"0PY0EFS"


@pytest.mark.parametrize("entry", FS1_DATA["ngham"], ids=lambda e: f"bit{e['bit_offset']}")
def test_fs1_paridade_rs_nao_bate_com_o_pyngham(entry):
    """Achado, congelado de propósito. Nos dois quadros, dados, cabeçalho,
    CRC e padding batem byte a byte com o que o PyNGHam codificaria — só os
    16 bytes de paridade diferem, e o RS não valida (-1). O CRC passa, então
    o pacote é aceito. O FS-2 não tem isso (teste do GOLDS-UFSC abaixo). Se
    um dia este número mudar, ou o PyNGHam mudou ou o adapter mudou."""
    assert LINK.decode(slice_of(entry)).rs_errors == -1


def test_fs1_bate_com_o_beacon_csv_do_decoder_oficial():
    """Os bytes do primeiro quadro, convertidos como o spacelab-decoder
    converte o pacote EPS do FS-1 (floripasat-1.json), dão a primeira linha
    do beacon.csv — 09:51:22, a mesma passagem."""
    pkt = LINK.decode(slice_of(FS1_DATA["ngham"][0])).payload
    word = lambda offset: (pkt[offset] << 8) | pkt[offset + 1]  # noqa: E731
    csv = FS1_DATA["beacon_csv_row_0951_22"].split(",")

    assert pkt[0] == 0x01  # pacote EPS do FS-1
    assert word(8) / 32 * 4.883e-3 == pytest.approx(float(csv[6]), abs=1e-5)       # bateria 1, V
    assert word(10) / 32 * 4.883e-3 == pytest.approx(float(csv[7]), abs=1e-5)      # bateria 2, V
    assert word(12) * 0.125 / 32 == pytest.approx(float(csv[8]))                   # monitor
    assert word(14) * 1.5625e-6 / 0.01 == pytest.approx(float(csv[9]))             # corrente, A
    assert word(18) * 6.25e-4 == pytest.approx(float(csv[10]))                     # carga, Ah
    eps_temp = (word(16) * 2.5 / 4095 - 0.680) * 70 / 0.170
    assert eps_temp == pytest.approx(float(csv[36]), abs=1e-3)                     # EPS, °C


def test_fs1_so_e_reconhecido_com_o_perfil_forcado():
    outcome = decode_packet(raw_packet(slice_of(FS1_DATA["ngham"][0]), radio="vhf"),
                            LINK, "teste", forced_profile=FS1)

    assert outcome.frame.status is FrameStatus.NOT_IMPLEMENTED
    assert (outcome.frame.sat_profile, outcome.frame.pkt_type) == ("fs1", "eps_beacon")


def test_fs1_quadro_ax25_nao_e_ngham():
    """O FS-1 alternava NGHam e AX.25 no mesmo syncword. O AX.25 tem de
    morrer no size tag, sem virar pacote."""
    frame = LINK.decode(slice_of(FS1_DATA["ax25"][0]))

    assert frame.payload is None
    assert frame.error == "size_tag"


# --- FS-2 (GOLDS-UFSC) ---------------------------------------------------------


def test_golds_ufsc_beacon_real_rs_limpo():
    frame = LINK.decode(slice_of(GOLDS["ngham"][0]))

    assert frame.rs_errors == 0
    assert len(frame.payload) == 65
    assert frame.payload[1:8] == b" PY0EFS"
    # 3 de size tag + 111 de codeword: exatamente o que a gravação trazia.
    assert frame.frame_length == GOLDS["ngham"][0]["bytes_available"]


def test_golds_ufsc_beacon_e_eps_beacon_ainda_sem_decoder():
    outcome = decode_packet(raw_packet(slice_of(GOLDS["ngham"][0]), radio="vhf"), LINK, "teste")
    frame = outcome.frame

    assert frame.status is FrameStatus.NOT_IMPLEMENTED
    assert (frame.sat_profile, frame.pkt_id, frame.pkt_type) == ("fs2", 0x00, "eps_beacon")
    assert frame.radio_mismatch is False
