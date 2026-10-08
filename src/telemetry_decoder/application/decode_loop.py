"""O laço: busca os pendentes, decodifica, grava. Tempo real e reprocessamento são o mesmo código.

    RawPacketSource.pending() -> decode_packet() -> TelemetryRepository.save()

"Pendente" é o raw packet sem linha em decoded_frames para a versão atual.
Por isso o mesmo laço serve para:

- o tempo real: a cada ~1 s, o que os archivers gravaram desde a última volta;
- o reprocessamento: subir DECODER_VERSION deixa o histórico inteiro pendente;
- o serviço que ficou fora do ar: na volta, tudo o que chegou enquanto isso.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter
from dataclasses import dataclass, field

from telemetry_decoder.application.decode_packet import decode_packet
from telemetry_decoder.domain.profiles import MissionProfile
from telemetry_decoder.domain.ports import LinkDecoder, RawPacketSource, TelemetryRepository

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 200
DEFAULT_POLL_INTERVAL_S = 1.0


@dataclass
class DecodeStats:
    processed: int = 0
    by_status: Counter = field(default_factory=Counter)


def decode_pending(source: RawPacketSource, link: LinkDecoder, repository: TelemetryRepository, *,
                   decoder_version: str, batch_size: int = DEFAULT_BATCH_SIZE,
                   since_id: int | None = None, radio: str | None = None,
                   forced_profile: MissionProfile | None = None,
                   stop: threading.Event | None = None) -> DecodeStats:
    """Esvazia os pendentes, lote por lote, e volta.

    Erro de banco SOBE: o lote não foi gravado, então continua pendente, e
    quem chamou decide quando tentar de novo. Erro de um pacote não sobe —
    vira linha com status `decoder_error` (ver decode_packet).
    """
    stats = DecodeStats()

    while stop is None or not stop.is_set():
        batch = source.pending(decoder_version, batch_size, since_id=since_id, radio=radio)

        for raw in batch:
            outcome = decode_packet(raw, link, decoder_version, forced_profile)
            repository.save(outcome)
            stats.processed += 1
            stats.by_status[outcome.frame.status.value] += 1

        if len(batch) < batch_size:
            break

    return stats


def run_forever(source: RawPacketSource, link: LinkDecoder, repository: TelemetryRepository, *,
                decoder_version: str, stop: threading.Event,
                poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
                batch_size: int = DEFAULT_BATCH_SIZE) -> None:
    """O serviço: uma rodada de `decode_pending` a cada `poll_interval_s`.

    Banco fora não derruba nada: loga, espera, tenta de novo. Nenhum pacote se
    perde, porque o cru está em raw_packets — o que não foi decodificado
    continua pendente.
    """
    failing = False

    while not stop.is_set():
        try:
            stats = decode_pending(source, link, repository, decoder_version=decoder_version,
                                   batch_size=batch_size, stop=stop)
            if failing:
                logger.info("Banco de volta.")
                failing = False
            if stats.processed:
                summary = ", ".join(f"{status} {n}" for status, n in sorted(stats.by_status.items()))
                logger.info("%d raw packet(s) decodificado(s): %s", stats.processed, summary)
        except Exception:  # noqa: BLE001 — banco instável: tentar de novo
            if not failing:
                logger.exception("Falha lendo ou gravando no banco; tentando de novo a cada %.0f s.",
                                 poll_interval_s)
            failing = True

        stop.wait(poll_interval_s)
