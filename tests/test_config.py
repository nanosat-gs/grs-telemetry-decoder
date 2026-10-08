from __future__ import annotations

import pytest

from telemetry_decoder.config import DEFAULT_API_PORT, load_config


def test_padroes():
    config = load_config({})

    assert config.database_url is None
    assert (config.api_port, config.poll_interval_s, config.batch_size) == (DEFAULT_API_PORT, 1.0, 200)


def test_do_ambiente():
    config = load_config({"PG_DATABASE_URL": "postgresql://x", "DECODER_POLL_INTERVAL_S": "0.5",
                          "DECODER_BATCH_SIZE": "50", "DECODER_API_PORT": "6000"})

    assert (config.database_url, config.poll_interval_s, config.batch_size, config.api_port) == (
        "postgresql://x", 0.5, 50, 6000)


@pytest.mark.parametrize("name, value", [
    ("DECODER_BATCH_SIZE", "muitos"), ("DECODER_BATCH_SIZE", "0"), ("DECODER_POLL_INTERVAL_S", "-1"),
])
def test_valor_invalido_derruba_o_boot(name, value):
    with pytest.raises(ValueError, match=name):
        load_config({name: value})
