"""Um raw packet, do começo ao fim: enlace -> cabeçalho -> perfil -> decoder do tipo.

Função pura sobre as portas: não toca banco nem relógio. Todo caminho termina
num DecodedFrame com status — inclusive os que não dão em telemetria.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from telemetry_decoder.domain import fsat_packet, profiles
from telemetry_decoder.domain.models import DecodedFrame, DecodeOutcome, FrameStatus, RawPacket
from telemetry_decoder.domain.packets.base import LayoutMismatch
from telemetry_decoder.domain.ports import LinkDecoder

logger = logging.getLogger(__name__)


def decode_packet(raw: RawPacket, link: LinkDecoder, decoder_version: str,
                  forced_profile: profiles.MissionProfile | None = None) -> DecodeOutcome:
    frame = DecodedFrame(
        raw_packet_id=raw.id,
        decoder_version=decoder_version,
        radio=raw.radio,
        received_at=raw.received_at,
        status=FrameStatus.NGHAM_FAILED,
    )

    try:
        return _decode(raw, link, frame, forced_profile)
    except Exception as error:  # noqa: BLE001 — um pacote não derruba o laço
        logger.exception("Erro decodificando o raw packet %d.", raw.id)
        return DecodeOutcome(replace(frame, status=FrameStatus.DECODER_ERROR,
                                     detail=f"{type(error).__name__}: {error}"))


def _decode(raw: RawPacket, link: LinkDecoder, frame: DecodedFrame,
            forced_profile: profiles.MissionProfile | None) -> DecodeOutcome:
    link_frame = link.decode(raw.payload)
    if not link_frame.ok:
        return DecodeOutcome(replace(frame, status=FrameStatus.NGHAM_FAILED,
                                     ngham_error=link_frame.error,
                                     frame_length=link_frame.frame_length))

    frame = replace(frame, rs_errors=link_frame.rs_errors,
                    frame_length=link_frame.frame_length, ngham_payload=link_frame.payload)

    packet = fsat_packet.parse(link_frame.payload)
    if packet is None:
        return DecodeOutcome(replace(frame, status=FrameStatus.MALFORMED,
                                     detail=f"{len(link_frame.payload)} bytes, menos que o cabeçalho"))

    frame = replace(frame, pkt_id=packet.pkt_id, callsign=packet.callsign)

    profile = profiles.resolve(packet.callsign, forced_profile)
    if profile is None:
        return DecodeOutcome(replace(frame, status=FrameStatus.UNKNOWN_SATELLITE))

    frame = replace(frame, sat_profile=profile.name,
                    pkt_type=profile.packet_type(packet.pkt_id),
                    radio_mismatch=profile.radio_mismatch(packet.pkt_id, raw.radio))

    if frame.pkt_type is None:
        return DecodeOutcome(replace(frame, status=FrameStatus.UNKNOWN_PACKET))

    decoder = profile.decoder(packet.pkt_id)
    if decoder is None:
        return DecodeOutcome(replace(frame, status=FrameStatus.NOT_IMPLEMENTED))

    try:
        record = decoder.decode(packet)
    except LayoutMismatch as error:
        return DecodeOutcome(replace(frame, status=FrameStatus.LAYOUT_MISMATCH, detail=str(error)))

    return DecodeOutcome(replace(frame, status=FrameStatus.OK), record=record, table=decoder.table)
