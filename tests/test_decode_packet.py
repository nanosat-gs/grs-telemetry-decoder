"""Um raw packet de ponta a ponta, sem banco: todo caminho termina num status."""

from __future__ import annotations

from frames import fsat, general_telemetry, junk, ngham_slice, raw_packet
from telemetry_decoder.adapters.pyngham_link import PyNghamLinkDecoder
from telemetry_decoder.application.decode_packet import decode_packet
from telemetry_decoder.domain.models import FrameStatus

LINK = PyNghamLinkDecoder()


def decode(payload: bytes, radio: str | None = "uhf", **kwargs):
    return decode_packet(raw_packet(payload, id=42, radio=radio), LINK, "teste", **kwargs)


def test_general_telemetry_pelo_uhf():
    outcome = decode(ngham_slice(general_telemetry()))
    frame = outcome.frame

    assert frame.status is FrameStatus.OK
    assert (frame.pkt_id, frame.pkt_type, frame.callsign) == (0x10, "general_telemetry", "PY0EFS")
    assert (frame.sat_profile, frame.radio_mismatch, frame.rs_errors) == ("fs2", False, 0)
    assert frame.ngham_payload == general_telemetry()
    assert frame.raw_packet_id == 42 and frame.decoder_version == "teste"
    assert outcome.table == "fs2_general_telemetry"
    assert outcome.record.values["eps_battery_current"] == -350


def test_radio_errado_decodifica_e_avisa():
    outcome = decode(ngham_slice(general_telemetry()), radio="vhf")

    assert outcome.frame.status is FrameStatus.OK
    assert outcome.frame.radio_mismatch is True


def test_tipo_conhecido_sem_decoder_fica_guardado():
    """O 0x13 (TC Feedback) ainda não tem decoder. O pacote não se perde: fica
    em decoded_frames com o payload, para o reprocessamento de amanhã."""
    packet = fsat(0x13, b"\x47\xff\xff\xff\xfe")

    outcome = decode(ngham_slice(packet))

    assert outcome.frame.status is FrameStatus.NOT_IMPLEMENTED
    assert outcome.frame.pkt_type == "tc_feedback"
    assert outcome.frame.ngham_payload == packet
    assert outcome.record is None


def test_id_que_o_perfil_nao_conhece():
    outcome = decode(ngham_slice(fsat(0x7F, b"\x00")))

    assert outcome.frame.status is FrameStatus.UNKNOWN_PACKET
    assert outcome.frame.pkt_id == 0x7F and outcome.frame.sat_profile == "fs2"


def test_outro_satelite():
    outcome = decode(ngham_slice(fsat(0x10, bytes(103), callsign=b" PU5GMA")))

    assert outcome.frame.status is FrameStatus.UNKNOWN_SATELLITE
    assert outcome.frame.callsign == "PU5GMA"


def test_pacote_menor_que_o_cabecalho():
    outcome = decode(ngham_slice(b"\x10 PY0"))

    assert outcome.frame.status is FrameStatus.MALFORMED
    assert outcome.frame.ngham_payload == b"\x10 PY0"


def test_ngham_falhou():
    outcome = decode(junk(255))

    assert outcome.frame.status is FrameStatus.NGHAM_FAILED
    assert outcome.frame.ngham_error == "size_tag"
    assert outcome.frame.ngham_payload is None


def test_comprimento_que_nao_e_layout():
    outcome = decode(ngham_slice(general_telemetry()[:110]))

    assert outcome.frame.status is FrameStatus.LAYOUT_MISMATCH
    assert "110 bytes" in outcome.frame.detail
    assert outcome.record is None


def test_excecao_num_decoder_vira_status_e_nao_sobe():
    class Quebrado:
        def decode(self, data):
            raise ZeroDivisionError("bug")

    outcome = decode_packet(raw_packet(b"x", id=7), Quebrado(), "teste")

    assert outcome.frame.status is FrameStatus.DECODER_ERROR
    assert "ZeroDivisionError" in outcome.frame.detail
