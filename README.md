# GRS Telemetry Decoder

Decodificador do downlink do **FloripaSat-2 (GOLDS-UFSC)** na estação terrena SpaceLab:
pega os raw packets que o caminho de recepção grava e entrega telemetria legível.

```
mission_control.raw_packets ─▶ NGHam (PyNGHam) ─▶ cabeçalho FSat ─▶ perfil ─▶ decoder do tipo
                                                                                 │
                       API :5592 ◀── decoded_frames + fs2_<tipo> ◀───────────────┘
                           │
                           └──▶ painel do operador (grs-manager, aba Telemetria)
```

- **Um serviço para os dois rádios.** Lê a tabela que os dois archivers (VHF e UHF)
  enchem, e não assina detector nenhum.
- **Um serviço para todos os tipos de pacote.** Cada tipo é um arquivo em
  `domain/packets/`, não um repositório. Hoje: General Telemetry (`0x10`). Os demais
  ficam gravados como `not_implemented` até ganharem decoder.
- **Nada se perde.** Todo raw packet ganha uma linha com status, decodificado ou não. Com
  o serviço fora, o cru continua no banco e é decodificado na volta.

## Rodar

Na estação, sobe com os profiles de recepção do `grs-station`:

```powershell
docker compose --profile rxsim up -d --build      # ou rx / rtlsdr
docker compose exec grs-telemetry-decoder python -m telemetry_decoder.main latest
curl http://localhost:5592/api/telemetry/fs2/general_telemetry/latest
```

Subcomandos (`python -m telemetry_decoder.main ...`):

| | |
|---|---|
| `serve` | laço de decodificação (a cada 1 s) + API em `:5592` |
| `decode [--since-id N] [--radio uhf] [--profile fs1]` | uma rodada sobre os pendentes e sai |
| `latest [--profile fs2] [--type general_telemetry]` | o mais recente, legível |
| `stats` | contagem por status, tipo e rádio |
| `decode-hex <hex>` | decodifica bytes colados, **sem banco** |

Ambiente:

| Variável | Padrão |
|---|---|
| `PG_DATABASE_URL` | obrigatória |
| `DECODER_POLL_INTERVAL_S` | `1.0` |
| `DECODER_BATCH_SIZE` | `200` |
| `DECODER_API_HOST` | `0.0.0.0` |
| `DECODER_API_PORT` | `5592` |
| `DECODER_SCHEMA_RETRY_S` | `10` |

## Desenvolver

```powershell
pip install -e ".[dev]"
python -m pytest -q
# o adapter Postgres contra um banco de verdade (schema descartável):
$env:TELEMETRY_TEST_DATABASE_URL = "postgresql+psycopg2://admin:admin@localhost:5432/tc_generator"
python -m pytest -q tests/test_postgres.py
```

## Documentos

- [`docs/packet-spec-fs2.md`](docs/packet-spec-fs2.md): a especificação dos pacotes, tirada
  do firmware.
- [`docs/schema-contract.md`](docs/schema-contract.md): tabelas, "pendente", versão e API.
- [`docs/adicionar-tipo-de-pacote.md`](docs/adicionar-tipo-de-pacote.md): o passo a passo
  para os próximos tipos.
- [`tests/fixtures/README.md`](tests/fixtures/README.md): os quadros reais e o que provam.

## Licença das dependências

O NGHam é o **PyNGHam** 1.1.1 (`mgm8/pyngham`, do SpaceLab), sob **LGPLv3**, importado como
biblioteca e sem modificação. Isso é o uso que a LGPL prevê. A versão é pinada exata porque
o adapter de enlace lê o estado interno do decodificador (ver
`adapters/pyngham_link.py`).

A fixture `golds_ufsc_beacon` vem de uma amostra do `spacelab-decoder` (GPL-3.0). Ela é
dado de teste, e o código dele não é usado.
