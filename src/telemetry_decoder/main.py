"""Ponto de entrada do GRS Telemetry Decoder.

    serve        o serviço: laço de decodificação + API de leitura (:5592)
    decode       uma rodada sobre os pendentes e sai (reprocessamento, regressão)
    latest       o pacote mais recente de um tipo, legível
    stats        contagem por status, tipo e rádio
    decode-hex   decodifica um raw packet colado na linha de comando, sem banco

`serve` e `decode` são o mesmo laço (application/decode_loop.py): o serviço é
só `decode` repetido a cada segundo.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from datetime import datetime, timezone
from types import FrameType

from telemetry_decoder import DECODER_VERSION
from telemetry_decoder.config import DecoderConfig, load_config
from telemetry_decoder.domain.profiles import PROFILES, get_profile

logger = logging.getLogger("telemetry_decoder")

_stop = threading.Event()


def _handle_signal(signum: int, _frame: FrameType | None) -> None:
    logger.info("Sinal %d recebido, encerrando.", signum)
    _stop.set()


def all_decoders():
    """Todo decoder de todo perfil, sem repetir tabela."""
    seen: dict[str, object] = {}
    for profile in PROFILES.values():
        for decoder in profile.decoders.values():
            seen.setdefault(decoder.table, decoder)
    return tuple(seen.values())


def build_store(config: DecoderConfig):
    if config.database_url is None:
        raise SystemExit("PG_DATABASE_URL não definida: o decodificador lê e escreve no Postgres.")

    from telemetry_decoder.adapters.postgres_store import PostgresStore

    return PostgresStore(config.database_url, all_decoders())


def prepare_schema(store, config: DecoderConfig, *, wait: bool) -> None:
    """Cria as tabelas e confere. Com `wait`, espera o raw_packets aparecer.

    O decodificador pode subir antes do archiver (ou contra um banco onde o
    caminho de recepção nunca rodou). Esperar é melhor que reiniciar em laço:
    o log diz uma vez o que falta, e o serviço começa sozinho quando o
    archiver criar a tabela.
    """
    from telemetry_decoder.adapters.postgres_store import RawPacketsMissing
    from telemetry_decoder.schema_check import check_schema

    warned = False
    while True:
        try:
            store.ensure_schema()
            break
        except RawPacketsMissing as error:
            if not wait:
                raise SystemExit(str(error)) from None
            if not warned:
                logger.warning("%s Esperando; nova tentativa a cada %.0f s.", error, config.schema_retry_s)
                warned = True
        except Exception:
            if not wait:
                raise
            logger.exception("Banco indisponível no boot; nova tentativa em %.0f s.", config.schema_retry_s)
        if _stop.wait(config.schema_retry_s):
            raise SystemExit(0)

    check_schema(store.engine, store.decoders)


def cmd_serve(args: argparse.Namespace, config: DecoderConfig) -> int:
    from telemetry_decoder.adapters.api import create_app
    from telemetry_decoder.adapters.pyngham_link import PyNghamLinkDecoder
    from telemetry_decoder.application.decode_loop import run_forever

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("decoder ........... %s", DECODER_VERSION)
    for profile in PROFILES.values():
        decoded = ", ".join(d.packet_type for d in profile.decoders.values()) or "nenhum"
        logger.info("perfil %-10s  %d tipos, com decoder: %s", profile.name, len(profile.packet_types), decoded)

    store = build_store(config)
    prepare_schema(store, config, wait=True)

    app = create_app(store, PROFILES, DECODER_VERSION)
    threading.Thread(
        target=app.run,
        # threaded=True pelo mesmo motivo do TC Scheduler: uma leitura lenta
        # não pode travar o healthcheck.
        kwargs={"host": config.api_host, "port": config.api_port,
                "debug": False, "use_reloader": False, "threaded": True},
        daemon=True,
    ).start()
    logger.info("API de leitura em http://%s:%d", config.api_host, config.api_port)

    run_forever(store, PyNghamLinkDecoder(), store, decoder_version=DECODER_VERSION, stop=_stop,
                poll_interval_s=config.poll_interval_s, batch_size=config.batch_size)
    store.close()
    return 0


def cmd_decode(args: argparse.Namespace, config: DecoderConfig) -> int:
    from telemetry_decoder.adapters.pyngham_link import PyNghamLinkDecoder
    from telemetry_decoder.application.decode_loop import decode_pending

    store = build_store(config)
    prepare_schema(store, config, wait=False)
    stats = decode_pending(store, PyNghamLinkDecoder(), store, decoder_version=DECODER_VERSION,
                           batch_size=config.batch_size, since_id=args.since_id, radio=args.radio,
                           forced_profile=get_profile(args.profile) if args.profile else None)
    print(f"{stats.processed} raw packet(s) decodificado(s) com o decoder {DECODER_VERSION}")
    for status, count in sorted(stats.by_status.items()):
        print(f"  {status:<18} {count}")
    store.close()
    return 0


def cmd_latest(args: argparse.Namespace, config: DecoderConfig) -> int:
    from telemetry_decoder.adapters.api import to_json_record

    profile = get_profile(args.profile)
    decoder = profile.decoder_by_type(args.type)
    if decoder is None:
        raise SystemExit(f"{args.profile} não tem decoder para {args.type!r}")

    store = build_store(config)
    rows = store.latest(decoder, profile.name, 1, DECODER_VERSION)
    store.close()
    if not rows:
        print(f"Nenhum {args.type} de {profile.name} decodificado ainda.")
        return 1

    record = to_json_record(decoder, rows[0])
    print(f"{args.type} — raw packet {record['raw_packet_id']}, recebido {record['received_at']} "
          f"pelo {record['radio']}, layout {record['layout']}, RS {record['rs_errors']}")
    for field in record["fields"]:
        print(f"  {field['name']:<28} {str(field['value']):>26} {field['display_unit']}")
    return 0


def cmd_stats(args: argparse.Namespace, config: DecoderConfig) -> int:
    store = build_store(config)
    print(json.dumps(store.stats(DECODER_VERSION), indent=2, default=str))
    store.close()
    return 0


def cmd_decode_hex(args: argparse.Namespace, config: DecoderConfig) -> int:
    """Sem banco: cole os bytes de um raw packet (os 255 depois do syncword)."""
    from telemetry_decoder.adapters.pyngham_link import PyNghamLinkDecoder
    from telemetry_decoder.application.decode_packet import decode_packet
    from telemetry_decoder.domain.models import RawPacket

    raw = RawPacket(id=0, received_at=datetime.now(timezone.utc), radio=args.radio,
                    payload=bytes.fromhex("".join(args.hex.split())))
    outcome = decode_packet(raw, PyNghamLinkDecoder(), DECODER_VERSION,
                            get_profile(args.profile) if args.profile else None)
    frame = outcome.frame
    print(f"status ......... {frame.status.value}")
    for name in ("ngham_error", "rs_errors", "frame_length", "pkt_id", "pkt_type", "callsign",
                 "sat_profile", "radio_mismatch", "detail"):
        value = getattr(frame, name)
        if value is not None:
            print(f"{name:<15}  {value:#04x}" if name == "pkt_id" else f"{name:<15}  {value}")
    if frame.ngham_payload is not None:
        print(f"payload ........ {frame.ngham_payload.hex()}")
    if outcome.record is not None:
        print(f"layout ......... {outcome.record.layout}")
        for name, value in outcome.record.values.items():
            print(f"  {name:<28} {value}")
    return 0 if outcome.record is not None else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telemetry_decoder", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="laço de decodificação + API")

    decode = sub.add_parser("decode", help="uma rodada sobre os pendentes")
    decode.add_argument("--since-id", type=int, help="só raw packets com id >= este")
    decode.add_argument("--radio", help="só deste rádio (vhf, uhf)")
    decode.add_argument("--profile", choices=sorted(PROFILES),
                        help="força o perfil, para qualquer callsign (gravações do FS-1)")

    latest = sub.add_parser("latest", help="o mais recente de um tipo")
    latest.add_argument("--profile", default="fs2", choices=sorted(PROFILES))
    latest.add_argument("--type", default="general_telemetry")

    sub.add_parser("stats", help="contagem por status, tipo e rádio")

    decode_hex = sub.add_parser("decode-hex", help="decodifica bytes colados, sem banco")
    decode_hex.add_argument("hex", help="os bytes depois do syncword, em hexadecimal")
    decode_hex.add_argument("--radio", help="rádio de origem, para conferir o esperado")
    decode_hex.add_argument("--profile", choices=sorted(PROFILES))

    return parser


COMMANDS = {"serve": cmd_serve, "decode": cmd_decode, "latest": cmd_latest,
            "stats": cmd_stats, "decode-hex": cmd_decode_hex}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args, load_config())


if __name__ == "__main__":
    sys.exit(main())
