"""O cabeçalho FSat e os perfis: quem é o satélite, que tipo é, se veio pelo rádio certo."""

from __future__ import annotations

import pytest

from frames import fsat
from telemetry_decoder.domain import fsat_packet, profiles
from telemetry_decoder.domain.packets.general_telemetry import DECODER
from telemetry_decoder.domain.profiles import FS1, FS2, MissionProfile
from telemetry_decoder.domain.satellite_enums import DownlinkId


def test_callsign_do_fs2_vem_com_espaco_a_esquerda():
    packet = fsat_packet.parse(fsat(0x10, b"\x01", callsign=b" PY0EFS"))

    assert (packet.pkt_id, packet.callsign, packet.length) == (0x10, "PY0EFS", 9)


def test_callsign_do_fs1_vinha_com_zero_a_esquerda():
    assert fsat_packet.parse(fsat(0x01, callsign=b"0PY0EFS")).callsign == "PY0EFS"


def test_menos_que_o_cabecalho_nao_e_pacote():
    assert fsat_packet.parse(b"\x10 PY0EF") is None


def test_fs2_conhece_todos_os_ids_de_downlink_e_decodifica_os_implementados():
    assert set(FS2.packet_types) == {member.value for member in DownlinkId}
    assert set(FS2.decoders) == {0x02, 0x10, 0x13}
    assert FS2.packet_type(0x14) == "param_value"
    assert FS2.decoder(0x14) is None


def test_nomes_de_tabela_unicos_e_com_prefixo_do_satelite():
    tables = [d.table for p in profiles.PROFILES.values() for d in p.decoders.values()]

    assert len(tables) == len(set(tables))
    assert all(decoder.table.startswith("fs2_") for decoder in FS2.decoders.values())


def test_resolve_pelo_callsign():
    assert profiles.resolve("PY0EFS") is FS2
    assert profiles.resolve("PU5GMA") is None


def test_fs1_so_quando_forcado():
    """O FS-1 usava o mesmo indicativo; ao vivo, todo PY0EFS é FS-2."""
    assert profiles.resolve("PY0EFS", forced=FS1) is FS1
    assert profiles.resolve("QUALQUER", forced=FS1) is FS1


@pytest.mark.parametrize("pkt_id, radio, mismatch", [
    (0x10, "uhf", False),
    (0x10, "vhf", True),
    (0x00, "vhf", False),
    (0x13, "vhf", True),    # o TC Feedback sai pelo TTC_0 (UHF)
    (0x14, "vhf", False),   # rádio do Param Value não está no perfil
    (0x10, None, False),    # linhas antigas, de antes da coluna radio
])
def test_radio_esperado(pkt_id, radio, mismatch):
    assert FS2.radio_mismatch(pkt_id, radio) is mismatch


def test_decoder_registrado_no_id_errado_falha_no_import():
    with pytest.raises(ValueError, match="ID errado"):
        MissionProfile(name="x", sat_id="x", description="", callsigns=frozenset({"X"}),
                       packet_types={0x11: "general_telemetry"}, decoders={0x11: DECODER})


def test_get_profile_desconhecido_lista_os_conhecidos():
    with pytest.raises(ValueError, match="fs1, fs2"):
        profiles.get_profile("fs3")
