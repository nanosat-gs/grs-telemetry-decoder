"""Enlace: o adapter PyNGHam contra quadros sintéticos de todos os tamanhos NGHam."""

from __future__ import annotations

import pytest

from frames import fsat, junk, ngham_slice
from telemetry_decoder.adapters.pyngham_link import PyNghamLinkDecoder

# Um tamanho de payload em cada um dos sete codewords NGHam, mais as bordas.
PAYLOAD_LENGTHS = (1, 28, 29, 60, 61, 92, 111, 124, 156, 188, 220)


@pytest.fixture
def link() -> PyNghamLinkDecoder:
    return PyNghamLinkDecoder()


@pytest.mark.parametrize("length", PAYLOAD_LENGTHS)
def test_quadro_limpo_de_todo_tamanho_volta_byte_a_byte(link, length):
    packet = junk(length)

    frame = link.decode(ngham_slice(packet))

    assert frame.payload == packet
    assert frame.rs_errors == 0
    assert frame.error is None


@pytest.mark.parametrize("length, decodes", [(188, True), (189, False), (220, False)])
def test_fatia_de_255_bytes_corta_os_maiores_quadros(link, length, decodes):
    """O detector publicava 255 bytes depois do syncword, "o maior quadro
    NGHam" — esquecendo os 3 do size tag. Payload acima de 188 bytes usa o
    codeword de 255 e não cabia: chegava cortado, sempre. Por isso a estação
    publica 258 (GRS_SYNCWORD_PACKET_BYTES no docker-compose do grs-station)."""
    frame = link.decode(ngham_slice(junk(length), total=255))

    assert (frame.payload is not None) is decodes
    if not decodes:
        assert (frame.error, frame.frame_length) == ("truncated", 258)


def test_o_lixo_depois_do_codeword_nao_entra_no_pacote(link):
    """A fatia tem 255 bytes; um General Telemetry ocupa 3 + 159. O resto é o
    começo do próximo pacote, ou ruído, e não pode ser lido."""
    packet = fsat(0x10, bytes(103))

    frame = link.decode(ngham_slice(packet))

    assert frame.payload == packet
    assert frame.frame_length == 3 + 159


def test_reed_solomon_corrige_e_conta(link):
    data = bytearray(ngham_slice(fsat(0x10, bytes(103))))
    for position in (10, 40, 90):
        data[position] ^= 0xFF

    frame = link.decode(bytes(data))

    assert frame.payload == fsat(0x10, bytes(103))
    assert frame.rs_errors == 3


def test_erro_alem_do_rs_e_recusado_pelo_crc(link):
    data = bytearray(ngham_slice(fsat(0x10, bytes(103))))
    for position in range(10, 60, 2):  # 25 bytes: o RS de 32 de paridade corrige 16
        data[position] ^= 0xA5

    frame = link.decode(bytes(data))

    assert frame.payload is None
    assert frame.error == "crc"


def test_size_tag_que_nao_bate_falha_sem_procurar_no_lixo(link):
    """O PyNGHam.decode() tentaria os 3 bytes seguintes como size tag, e os
    seguintes, pelo lixo adentro. Aqui é uma tentativa só."""
    data = b"\x00\x00\x00" + ngham_slice(fsat(0x10, bytes(103)))

    frame = link.decode(data[:255])

    assert frame.payload is None
    assert frame.error == "size_tag"


def test_size_tag_tolera_erro_de_bit(link):
    data = bytearray(ngham_slice(fsat(0x10, bytes(103))))
    data[0] ^= 0b0000_0101  # dois bits; o NGHam aceita até 6

    assert link.decode(bytes(data)).payload == fsat(0x10, bytes(103))


@pytest.mark.parametrize("cut", [0, 2, 3, 100])
def test_quadro_cortado(link, cut):
    frame = link.decode(ngham_slice(fsat(0x10, bytes(103)))[:cut])

    assert frame.payload is None
    assert frame.error == "truncated"


def test_uma_falha_nao_contamina_o_proximo_pacote(link):
    """O PyNGHam guarda estado entre bytes; o adapter tem de zerá-lo."""
    link.decode(ngham_slice(fsat(0x10, bytes(103)))[:50])
    link.decode(b"\x00" * 255)

    assert link.decode(ngham_slice(fsat(0x13, b"\x40\x00"))).payload == fsat(0x13, b"\x40\x00")
