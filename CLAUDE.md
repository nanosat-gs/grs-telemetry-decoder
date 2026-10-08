# Contexto do projeto

GRS Telemetry Decoder: o decodificador do downlink do FloripaSat-2 (GOLDS-UFSC). Fecha a
metade "decodificação" da estação: os raw packets que o `grs-packet-archiver` grava
viram telemetria no banco, na API e no painel do operador.

**Estado:** fatia de decodificação entregue para o General Telemetry (`0x10`). **O
escopo final é o satélite inteiro:**

- todos os tipos de downlink, do `0x00` ao `0x15`;
- o beacon do EPS2;
- o SBCD.

Tudo isso entra **neste** serviço, um arquivo por tipo. Nenhum tipo ganha repositório
próprio.

## Desenho

Hexagonal, como o resto da estação.

```
domain/     models.py        RawPacket, LinkFrame, FsatPacket, TelemetryRecord, DecodedFrame, FrameStatus
            ports.py         RawPacketSource, LinkDecoder, PacketDecoder, TelemetryRepository, TelemetryReader
            fsat_packet.py   cabeçalho comum: ID + callsign (spec §2)
            satellite_enums.py  IDs de pacote e enums (spec §3, §5, §6)
            profiles.py      MissionProfile FS-2 e FS-1: tipos, rádio esperado, registro de decoders
            packets/         UM ARQUIVO POR TIPO — base.py (FixedLayoutDecoder) + general_telemetry.py
            units.py         K->°C, mV->V, epoch->ISO; só na saída
adapters/   pyngham_link.py  LinkDecoder: NGHam pelo PyNGHam, com size tag estrito
            postgres_store.py  RawPacketSource + TelemetryRepository + TelemetryReader
            api.py           Flask, :5592, genérica por tipo
application/ decode_packet.py   um raw packet -> DecodeOutcome (função pura)
            decode_loop.py   pendentes -> decode -> save; o mesmo laço para tempo real e reprocessamento
schema_check.py  derruba o boot se o banco divergir
config.py   ambiente
main.py     serve | decode | latest | stats | decode-hex
```

## Decisões, e por quê

**Lê `raw_packets`, não a `:5558`.**

- Uma fonte só para os dois rádios.
- Nada se perde com o decoder fora.
- O reprocessamento é o mesmo código do tempo real.
- Latência de ~1 s não importa para telemetria a cada 60 s.

**"Pendente" é anti-join, nunca cursor por id.** Os archivers gravam em lote, cada lote
numa transação. Com os dois gravando juntos, um id menor fica visível depois de um maior,
e um cursor pularia pacotes para sempre, sem erro. Está provado em
`tests/test_postgres.py::test_commits_cruzados...`; o detalhe está em
`docs/schema-contract.md`.

**Todo raw packet ganha linha em `decoded_frames`**, com um destes status: `ok`,
`ngham_failed`, `malformed`, `unknown_satellite`, `unknown_packet`, `not_implemented`,
`layout_mismatch` ou `decoder_error`. Um ID conhecido sem decoder não se perde: o payload
fica guardado e vira telemetria quando o decoder existir e a `DECODER_VERSION` subir.

**O tipo de pacote é descrito por uma tabela de campos (`Field`), não por código de
parse.** Da mesma tabela saem:

- as colunas do banco;
- o INSERT;
- o `schema_check`;
- a API.

Tipo novo não toca no cano. Passo a passo em `docs/adicionar-tipo-de-pacote.md`.

**Valor cru no banco, conversão na API.** O inteiro do satélite é o dado; °C e V são
apresentação.

**Ordenação por `received_at`, não por `sat_time`.** O archiver carimba na chegada, então
um lote atrasado não passa na frente de nada. E o relógio do satélite volta num reset do
OBDH.

**Size tag conferido uma vez só.** O `PyNGHam.decode()` sairia procurando size tag pelo
lixo depois do quadro, e poderia achar telemetria inventada com CRC válido por acaso. O
adapter alimenta o decodificador byte a byte e olha o estado interno. Por isso o PyNGHam
está pinado em versão exata.

**Dois layouts do `0x10`:** 111 bytes (firmware atual) e 105 (o que o
`spacelab-decoder` descreve). Não se sabe qual voa.

**A corrente da bateria é `int16`**, como o decoder da equipe do satélite lê, embora o
firmware guarde em `uint16`. Confirmar com o EPS. O payload guardado permite reprocessar.

## Achados que este repositório fez

- **A fatia do detector cortava os maiores quadros.** Eram 255 bytes depois do syncword,
  mas o maior quadro NGHam tem 3 de size tag + 255 de codeword. Payload acima de 188 bytes
  nunca decodificava. Corrigido no `docker-compose.yml` do `grs-station`
  (`RX_PACKET_BYTES=258`); ver `tests/test_link.py`.
- **O FS-1 tem paridade RS diferente da do PyNGHam** (CRC ok, RS `-1`). O FS-2 não tem:
  o quadro real do GOLDS-UFSC dá 0 correções. Ver `tests/fixtures/README.md`.

## Testes

```powershell
python -m pytest -q                       # unitários + quadros reais, sem banco
$env:TELEMETRY_TEST_DATABASE_URL = "postgresql+psycopg2://admin:admin@localhost:5432/tc_generator"
python -m pytest -q tests/test_postgres.py
```

No `grs-station`, o `tests/test_telemetry_offline_e2e.py` faz a cadeia inteira: simulador →
IQ com ruído → demodulador real → syncword → este decoder, campo a campo.

## Em aberto

- Qual firmware do OBDH voa (111 ou 105 bytes).
- Sinal da corrente da bateria; escala do RSSI e da corrente acumulada.
- Próximos tipos, na ordem sugerida:
  1. os simples do OBDH (`0x02`, `0x13`, `0x14`, `0x01`/`0x15`);
  2. o beacon do EPS2 (`0x00`), que exige levantar o firmware do EPS2;
  3. `0x11` e `0x12`, de layout variável;
  4. o SBCD.
- Escala do anti-join: ver `docs/schema-contract.md` se o `raw_packets` passar de milhões
  de linhas.
