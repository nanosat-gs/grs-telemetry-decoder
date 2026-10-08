"""API HTTP de leitura (porta 5592). Flask, como a do TC Scheduler.

Genérica por tipo: a rota é /api/telemetry/<perfil>/<tipo>, e o <tipo> sai do
registro do perfil. Um decoder novo aparece aqui sem rota nova.

    GET /api/health
    GET /api/telemetry                              perfis, tipos e quem já tem decoder
    GET /api/telemetry/<perfil>/<tipo>/latest       o mais recente
    GET /api/telemetry/<perfil>/<tipo>?limit=N      os N mais recentes (máx. 1000)
    GET /api/decoder/stats                          contagem por status, tipo e rádio

Erros: 404 para perfil ou tipo desconhecido, 501 para tipo conhecido ainda
sem decoder, 503 para banco fora.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime

from flask import Flask, jsonify, request

from telemetry_decoder.domain.ports import PacketDecoder, TelemetryReader
from telemetry_decoder.domain.profiles import MissionProfile
from telemetry_decoder.domain.units import humanize

logger = logging.getLogger(__name__)

MAX_LIMIT = 1000


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def to_json_record(decoder: PacketDecoder, row: Mapping) -> dict:
    return {
        "raw_packet_id": row["raw_packet_id"],
        "decoded_frame_id": row["decoded_frame_id"],
        "decoder_version": row["decoder_version"],
        "received_at": _iso(row["received_at"]),
        "sat_time": _iso(row["sat_time"]),
        "radio": row["radio"],
        "layout": row["layout"],
        "callsign": row["callsign"],
        "rs_errors": row["rs_errors"],
        "radio_mismatch": row["radio_mismatch"],
        "fields": [_field(field, row[field.name]) for field in decoder.fields],
    }


def _field(field, raw) -> dict:
    value, display_unit = humanize(field, raw)
    return {"name": field.name, "raw": raw, "unit": field.unit, "value": value,
            "display_unit": display_unit, "description": field.description}


def create_app(reader: TelemetryReader, profiles: Mapping[str, MissionProfile],
               decoder_version: str) -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False

    def resolve(profile_name: str, packet_type: str):
        profile = profiles.get(profile_name)
        if profile is None:
            return None, (jsonify({"error": f"perfil {profile_name} desconhecido"}), 404)
        if packet_type not in profile.packet_types.values():
            return None, (jsonify({"error": f"{profile_name} não tem o tipo {packet_type}"}), 404)
        decoder = profile.decoder_by_type(packet_type)
        if decoder is None:
            # Os pacotes deste tipo ESTÃO no banco, como `not_implemented`.
            return None, (jsonify({"error": f"{packet_type} ainda sem decoder",
                                   "status": "not_implemented"}), 501)
        return decoder, None

    def read(action):
        try:
            return action()
        except Exception:  # noqa: BLE001
            logger.exception("Leitura falhou.")
            return jsonify({"error": "banco indisponível"}), 503

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "decoder_version": decoder_version})

    @app.get("/api/telemetry")
    def catalog():
        return jsonify({
            name: {
                "sat_id": profile.sat_id,
                "description": profile.description,
                "types": [
                    {"pkt_id": pkt_id, "packet_type": packet_type,
                     "decoder": profile.decoder(pkt_id) is not None,
                     "expected_radio": profile.expected_radio.get(pkt_id)}
                    for pkt_id, packet_type in sorted(profile.packet_types.items())
                ],
            }
            for name, profile in profiles.items()
        })

    @app.get("/api/telemetry/<profile_name>/<packet_type>/latest")
    def latest(profile_name: str, packet_type: str):
        decoder, error = resolve(profile_name, packet_type)
        if error:
            return error

        def action():
            rows = reader.latest(decoder, profile_name, 1, decoder_version)
            return jsonify({"record": to_json_record(decoder, rows[0]) if rows else None})

        return read(action)

    @app.get("/api/telemetry/<profile_name>/<packet_type>")
    def history(profile_name: str, packet_type: str):
        decoder, error = resolve(profile_name, packet_type)
        if error:
            return error
        try:
            limit = int(request.args.get("limit", 50))
        except ValueError:
            return jsonify({"error": "limit precisa ser inteiro"}), 400
        if not 1 <= limit <= MAX_LIMIT:
            return jsonify({"error": f"limit entre 1 e {MAX_LIMIT}"}), 400

        def action():
            rows = reader.latest(decoder, profile_name, limit, decoder_version)
            return jsonify({"records": [to_json_record(decoder, row) for row in rows]})

        return read(action)

    @app.get("/api/decoder/stats")
    def stats():
        def action():
            result = reader.stats(decoder_version)
            result["last_decoded_at"] = _iso(result.get("last_decoded_at"))
            for row in result.get("by_type", []):
                row["last_received_at"] = _iso(row.get("last_received_at"))
            return jsonify(result)

        return read(action)

    return app
