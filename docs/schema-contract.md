# Contrato de dados do GRS Telemetry Decoder

O que o decodificador lê, o que escreve e o que serve. Mudar qualquer coisa daqui é
mudar o contrato: a API, as tabelas e o painel do operador dependem disto.

## O que lê: `mission_control.raw_packets`

Dono: **`grs-packet-archiver`** (`grs-iq-recorder`, `postgres_packet_archive.py`). Os
dois archivers, VHF e UHF, gravam na mesma tabela.

O decoder só lê estas colunas (o `schema_check` confere só estas):

| Coluna | Uso |
|---|---|
| `id` | Chave do raw packet; vira `raw_packet_id` nas tabelas do decoder |
| `received_at` | Relógio da estação na chegada ao archiver. Copiado, e usado para ordenar |
| `radio` | `vhf` / `uhf`. Copiado; confere o rádio esperado do tipo |
| `payload` | Os bytes depois do syncword (258), que vão ao NGHam |

Sem a tabela, o archiver nunca subiu contra este banco. O `serve` espera e avisa uma
vez; o `decode` sai com a mensagem.

### "Pendente": anti-join, nunca cursor por id

Um raw packet está pendente quando não tem linha em `decoded_frames` para o
`DECODER_VERSION` atual:

```sql
SELECT r.id, r.received_at, r.radio, r.payload
FROM mission_control.raw_packets r
WHERE NOT EXISTS (SELECT 1 FROM mission_control.decoded_frames d
                  WHERE d.raw_packet_id = r.id AND d.decoder_version = :v)
ORDER BY r.id LIMIT :lote
```

**Por que não "id maior que o último lido":**

- Os archivers gravam em lote (até 50 pacotes ou 1 s), cada lote numa transação.
- O `BIGSERIAL` reserva o id no INSERT, e a linha só fica visível no COMMIT.
- Com os dois archivers gravando juntos, o UHF pode reservar 100–110 e o VHF o 111. Se o
  VHF fizer commit primeiro, o decoder lê o 111. Quando o UHF fizer commit, um cursor já
  estaria depois do 110.
- **Os pacotes 100–110 seriam pulados para sempre, sem erro.** O teste
  `test_commits_cruzados_dos_dois_archivers_nao_perdem_pacote` reproduz isso contra
  Postgres de verdade.

**Custo:** o anti-join percorre `raw_packets` a cada rodada (1 s). Nas taxas da estação,
são milhares de pacotes por dia e cerca de um milhão por ano, e isso cabe com folga. Se um
dia não couber, o caminho é uma marca d'água com atraso: ignorar ids abaixo do menor
pendente de alguns minutos atrás. Um cursor simples não serve.

## O que escreve

Tudo no schema `mission_control`, criado no boot com `CREATE TABLE IF NOT EXISTS`. Não há
UPDATE nem DELETE.

### `decoded_frames`: uma linha por raw packet, por versão do decoder

Toda linha de `raw_packets` termina aqui, decodificada ou não:

| Coluna | Tipo | |
|---|---|---|
| `id` | `BIGSERIAL` PK | |
| `raw_packet_id` | `BIGINT NOT NULL` → `raw_packets(id)` | |
| `decoder_version` | `TEXT NOT NULL` | `UNIQUE (raw_packet_id, decoder_version)` |
| `radio` | `TEXT` | copiado de `raw_packets` |
| `received_at` | `TIMESTAMPTZ NOT NULL` | copiado de `raw_packets` |
| `status` | `TEXT NOT NULL` | ver abaixo |
| `ngham_error` | `TEXT` | `size_tag` / `truncated` / `crc` |
| `rs_errors` | `INTEGER` | símbolos corrigidos; `-1` = RS não validou mas o CRC passou |
| `frame_length` | `INTEGER` | bytes do raw packet que o quadro ocupou (3 + codeword) |
| `ngham_payload` | `BYTEA` | o pacote FSat, já sem NGHam |
| `pkt_id`, `pkt_type`, `callsign`, `sat_profile` | | do cabeçalho e do perfil |
| `radio_mismatch` | `BOOLEAN` | o tipo chegou por um rádio diferente do esperado |
| `detail` | `TEXT` | motivo legível (`layout_mismatch`, `decoder_error`...) |
| `decoded_at` | `TIMESTAMPTZ` | |

Valores de `status`:

| `status` | Significado |
|---|---|
| `ok` | Decodificado. Tem linha na tabela do tipo |
| `ngham_failed` | Size tag, quadro cortado ou CRC |
| `malformed` | Passou no NGHam com menos de 8 bytes (o cabeçalho) |
| `unknown_satellite` | Callsign que nenhum perfil reconhece |
| `unknown_packet` | Satélite nosso, ID que o perfil não conhece |
| `not_implemented` | ID conhecido sem decoder: o `ngham_payload` fica guardado |
| `layout_mismatch` | Comprimento que não é nenhum dos layouts do tipo |
| `decoder_error` | Exceção dentro de um decoder (bug nosso); o laço segue |

### `fs2_<tipo>`: uma tabela por tipo de pacote

Nesta versão:

| Tabela | Tipo | Desde |
|---|---|---|
| `fs2_general_telemetry` | `0x10` General Telemetry | 0.1.0 |
| `fs2_ping_answer` | `0x02` Ping Answer (pong) | 0.2.0 |
| `fs2_tc_feedback` | `0x13` TC Feedback | 0.2.0 |

O cabeçalho é comum a todas as tabelas de tipo:

| Coluna | Tipo |
|---|---|
| `decoded_frame_id` | `BIGINT` PK → `decoded_frames(id)` |
| `raw_packet_id`, `decoder_version`, `received_at`, `radio`, `sat_profile` | copiados |
| `sat_time` | `TIMESTAMPTZ`: o relógio do satélite, quando o tipo tem um |
| `layout` | `TEXT`: `obdh2-111`, `obdh2-105`... |

Os campos do decoder vêm em seguida, um por coluna, com o tipo SQL saído do formato do
campo:

| Formato | Tipo SQL |
|---|---|
| `uint8`, `int8`, `int16` | `SMALLINT` |
| `uint16`, `int32` | `INTEGER` |
| `uint32` | `BIGINT` |
| `char[7]` (indicativo, formato `7s`) | `TEXT`, sem o preenchimento |

**O valor gravado é o inteiro do satélite**, sem conversão de unidade.

**Campo novo num decoder** vira coluna no próximo boot (`ADD COLUMN IF NOT EXISTS`). As
linhas antigas ficam NULL, que é a verdade: aquele layout não trazia o campo. **Mudar o
tipo** de um campo existente não é automático: o `schema_check` derruba o boot com a lista
do que diverge, e a migração é decisão de alguém.

### Versão do decoder e reprocessamento

- `DECODER_VERSION` está em `src/telemetry_decoder/__init__.py`. Subir a versão faz o
  histórico inteiro ficar pendente de novo.
- O serviço decodifica tudo outra vez a partir de `raw_packets`, ao lado das linhas antigas.
- As leituras da API filtram pela versão atual.
- Subir a versão é o jeito de levar uma correção de layout aos pacotes que já estavam no
  banco, e de transformar os `not_implemented` de ontem em telemetria.

## Quem mais lê estas tabelas

O **TC Scheduler** (módulo `tc_lifecycle`) lê `decoded_frames` e `fs2_tc_feedback` para
casar cada resposta do satélite com o telecomando que a provocou e mudar o status dele.
Ver `uplink-pares-e-estados-fs2.md` §3.

| Tabela | Colunas que ele lê |
|---|---|
| `decoded_frames` | `id`, `raw_packet_id`, `decoder_version`, `received_at`, `radio`, `status`, `ngham_payload`, `pkt_id`, `sat_profile`, `detail` |
| `fs2_tc_feedback` | `decoded_frame_id`, `requester_callsign`, `tc_id`, `error_code` |

Renomear ou remover alguma dessas quebra o casamento. O `schema_check` do Scheduler
confere no boot dele.

## O que serve: API HTTP (`:5592`, só `127.0.0.1` no host)

| Rota | Resposta |
|---|---|
| `GET /api/health` | `{"ok": true, "decoder_version": ...}` |
| `GET /api/telemetry` | Perfis, tipos, quem tem decoder e o rádio esperado |
| `GET /api/telemetry/<perfil>/<tipo>/latest` | `{"record": {...}}`, ou `{"record": null}` se ainda não há |
| `GET /api/telemetry/<perfil>/<tipo>?limit=N` | `{"records": [...]}`, N de 1 a 1000 (padrão 50) |
| `GET /api/decoder/stats` | Contagem por status e por tipo/rádio, pendentes, última decodificação |

Erros:

- `404`: perfil ou tipo desconhecido;
- `501`: tipo conhecido ainda sem decoder;
- `400`: `limit` inválido;
- `503`: banco fora.

**Ordem:** do mais recente para o mais antigo por `received_at`, o relógio da estação, e
não por `sat_time`:

- o archiver carimba na chegada, então um lote gravado com atraso não passa na frente de nada;
- o relógio do satélite volta para trás num reset do OBDH.

Cada registro:

```json
{
  "raw_packet_id": 1234, "decoded_frame_id": 987, "decoder_version": "0.1.0",
  "received_at": "2026-10-06T12:00:00.123456+00:00", "sat_time": "2026-10-06T11:59:58+00:00",
  "radio": "uhf", "layout": "obdh2-111", "callsign": "PY0EFS",
  "rs_errors": 0, "radio_mismatch": false,
  "fields": [
    {"name": "obdh_mcu_temp", "raw": 298, "unit": "K", "value": 24.85,
     "display_unit": "°C", "description": "Temperatura do µC do OBDH"}
  ]
}
```

`fields` vem na ordem do pacote. A conversão está em `domain/units.py`:

| Unidade | Vira |
|---|---|
| K | °C |
| mV | V |
| s (epoch) | ISO 8601, ou `null` para 0 ("nunca") |
| outras | o valor como veio |
