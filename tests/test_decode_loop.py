"""O laço, com fonte e repositório em memória."""

from __future__ import annotations

import threading

import pytest

from frames import fsat, general_telemetry, junk, ngham_slice, raw_packet
from telemetry_decoder.adapters.pyngham_link import PyNghamLinkDecoder
from telemetry_decoder.application.decode_loop import decode_pending, run_forever


class MemoryStore:
    """RawPacketSource + TelemetryRepository sobre listas, com a mesma
    semântica do Postgres: pendente = sem linha para a versão."""

    def __init__(self, raws):
        self.raws = list(raws)
        self.saved = {}  # (raw_packet_id, version) -> outcome
        self.pending_calls = 0
        self.fail_reads = 0

    def pending(self, decoder_version, limit, since_id=None, radio=None):
        self.pending_calls += 1
        if self.fail_reads:
            self.fail_reads -= 1
            raise ConnectionError("banco fora")
        rows = [r for r in sorted(self.raws, key=lambda r: r.id)
                if (r.id, decoder_version) not in self.saved
                and (since_id is None or r.id >= since_id)
                and (radio is None or r.radio == radio)]
        return rows[:limit]

    def save(self, outcome):
        key = (outcome.frame.raw_packet_id, outcome.frame.decoder_version)
        if key in self.saved:
            return False
        self.saved[key] = outcome
        return True


def mixed(n):
    """n pacotes alternando os casos: GT pelo UHF, TC Feedback, lixo."""
    payloads = [ngham_slice(general_telemetry()), ngham_slice(fsat(0x13, b"\x47\x00")), junk(255)]
    return [raw_packet(payloads[i % 3], id=i + 1, radio="uhf") for i in range(n)]


def test_esvazia_os_pendentes_em_lotes():
    store = MemoryStore(mixed(25))

    stats = decode_pending(store, PyNghamLinkDecoder(), store, decoder_version="v1", batch_size=10)

    assert stats.processed == 25
    assert dict(stats.by_status) == {"ok": 9, "not_implemented": 8, "ngham_failed": 8}
    assert store.pending_calls == 3


def test_segunda_rodada_nao_refaz_nada():
    store = MemoryStore(mixed(5))
    link = PyNghamLinkDecoder()
    decode_pending(store, link, store, decoder_version="v1")

    assert decode_pending(store, link, store, decoder_version="v1").processed == 0


def test_versao_nova_reprocessa_o_historico_ao_lado_do_antigo():
    store = MemoryStore(mixed(5))
    link = PyNghamLinkDecoder()
    decode_pending(store, link, store, decoder_version="v1")

    assert decode_pending(store, link, store, decoder_version="v2").processed == 5
    assert len(store.saved) == 10


def test_filtros_de_reprocessamento():
    raws = mixed(6) + [raw_packet(ngham_slice(general_telemetry()), id=99, radio="vhf")]
    store = MemoryStore(raws)

    stats = decode_pending(store, PyNghamLinkDecoder(), store, decoder_version="v1",
                           since_id=4, radio="uhf")

    assert sorted(key[0] for key in store.saved) == [4, 5, 6]
    assert stats.processed == 3


def test_erro_de_banco_sobe():
    store = MemoryStore(mixed(3))
    store.fail_reads = 1

    with pytest.raises(ConnectionError):
        decode_pending(store, PyNghamLinkDecoder(), store, decoder_version="v1")


def test_servico_sobrevive_ao_banco_fora_e_decodifica_na_volta():
    store = MemoryStore(mixed(3))
    store.fail_reads = 2
    stop = threading.Event()

    def stop_when_done():
        while len(store.saved) < 3 and not stop.wait(0.01):
            pass
        stop.set()

    watcher = threading.Thread(target=stop_when_done)
    watcher.start()
    run_forever(store, PyNghamLinkDecoder(), store, decoder_version="v1", stop=stop,
                poll_interval_s=0.01)
    watcher.join(timeout=5)

    assert len(store.saved) == 3
    assert store.pending_calls >= 3
