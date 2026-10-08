"""Conversão para leitura humana. Só na saída: o banco guarda o inteiro do satélite.

Por unidade, não por campo — todo campo em K vira °C do mesmo jeito (spec §7).
Um tipo novo com uma unidade nova precisa de uma linha aqui; sem ela, o valor
sai como veio, o que é feio mas não é errado.
"""

from __future__ import annotations

from datetime import datetime, timezone

from telemetry_decoder.domain.packets.base import Field


def humanize(field: Field, raw: int | None) -> tuple[object, str]:
    """:return: (valor, unidade) para mostrar."""
    if raw is None:
        return None, field.unit

    if field.unit == "K":
        return round(raw - 273.15, 2), "°C"
    if field.unit == "mV":
        return round(raw / 1000, 3), "V"
    if field.unit == "s":
        # Instantes do satélite em Unix epoch. 0 é "nunca aconteceu" (último
        # contato, próxima TC agendada), não 1970.
        if raw == 0:
            return None, "UTC"
        return datetime.fromtimestamp(raw, tz=timezone.utc).isoformat(), "UTC"

    return raw, field.unit
