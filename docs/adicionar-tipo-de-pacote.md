# Como adicionar um tipo de pacote

O decoder nasceu com o General Telemetry (`0x10`), mas o serviço é o decodificador de
**todo** o downlink do FS-2. Cada tipo novo é um arquivo, uma linha no perfil e um
teste. **O cano não muda:** enlace, fonte, laço, banco, API e painel continuam iguais.

Desde o primeiro dia, os pacotes de tipos sem decoder ficam gravados como
`not_implemented`, com o payload. Quando o decoder do tipo existir, eles viram
telemetria no reprocessamento.

## 1. Levantar o layout no firmware

Escreva a tabela byte a byte em `docs/packet-spec-fs2.md`. A fonte é o firmware: o
`.c` que monta o pacote no OBDH2, ou no EPS2 para o beacon. Não use a memória nem o JSON
do `spacelab-decoder`, que já mostrou estar defasado (o `0x10` de 105 bytes). Registre o
arquivo e o commit.

## 2. O decoder: `src/telemetry_decoder/domain/packets/<tipo>.py`

Layout fixo é dado, não código. O exemplo é o do TC Feedback
(`src/telemetry_decoder/domain/packets/tc_feedback.py`), levantado do `send_tc_feedback`
do `process_tc.c`:

```python
from telemetry_decoder.domain.packets.base import Field, FixedLayoutDecoder
from telemetry_decoder.domain.satellite_enums import DownlinkId

FIELDS = (
    # offset contado do INÍCIO do pacote (coluna "Frame" da spec), big-endian
    Field("requester_callsign", 8, "7s", "", "Indicativo de quem mandou o telecomando"),
    Field("tc_id", 15, "B", "", "ID do telecomando a que o feedback responde (UplinkId)"),
    Field("sat_timestamp", 16, "I", "s", "Relógio do satélite na execução"),
    Field("error_code", 20, "h", "", "Resultado: 0 sucesso, negativo = erro (TcFeedbackCode)"),
)

DECODER = FixedLayoutDecoder(
    pkt_id=DownlinkId.TC_FEEDBACK,
    packet_type=DownlinkId.TC_FEEDBACK.packet_type,   # "tc_feedback"
    table="fs2_tc_feedback",
    fields=FIELDS,
    layouts={22: "obdh2-22"},       # comprimento total -> nome do layout
    sat_time_field="sat_timestamp",
    source="obdh2 firmware/app/tasks/process_tc.c, send_tc_feedback (v1.0, 3f0ad36)",
)
```

- **Formatos:** `B` uint8, `b` int8, `H` uint16, `h` int16, `I` uint32, `i` int32, e `7s` para
  um indicativo de 7 bytes (vira texto sem o preenchimento). Cada um define o tipo da coluna.
- **Unidades:** `K`, `mV`, `mA`, `s` (epoch), `%`, `deg`, `km`. Unidade nova precisa de uma
  linha em `domain/units.py`, ou sai crua na API.
- **`sat_time_field`:** o campo que tem o relógio do satélite, se houver.
- **Erro na tabela de campos derruba o import:** sobreposição, nome repetido ou campo além
  do maior layout.

Tipo de layout variável, como o `0x11`, que muda com o `data_id`, ou o `0x12`, com o
`table_id`: implemente a porta `PacketDecoder` (`domain/ports.py`) direto. Ela precisa de
`pkt_id`, `packet_type`, `table`, `fields` (o conjunto de colunas) e
`decode(FsatPacket) -> TelemetryRecord`.

## 3. Registrar: `domain/profiles.py`

```python
decoders=MappingProxyType({
    DownlinkId.GENERAL_TELEMETRY: general_telemetry.DECODER,
    DownlinkId.TC_FEEDBACK: tc_feedback.DECODER,          # <- a linha nova
}),
```

Se o rádio do tipo for conhecido, acrescente-o também a `expected_radio`.

## 4. Testar: `tests/test_<tipo>.py`

- **Cobertura do layout:** todo byte de dados pertence a exatamente um campo. Veja
  `test_os_campos_cobrem_os_103_bytes_de_dados_sem_buraco`.
- **Offsets conferidos um a um** contra a coluna "Frame" da spec.
- **Ida e volta:** monte o pacote com `tests/frames.py` (`fsat()` + `ngham_slice()`) e
  confira valor por valor, incluindo negativos e máximos.
- **Comprimento inválido** vira `layout_mismatch`.
- **Se houver gravação real do tipo**, ela entra em `tests/fixtures/real_frames.json` pelo
  `tools/extract_ngham_slices.py`. Um quadro real vale mais que dez sintéticos.

## 5. Subir `DECODER_VERSION`

Suba a versão em `src/telemetry_decoder/__init__.py`. No próximo boot:

- a tabela `fs2_<tipo>` é criada sozinha;
- o histórico inteiro fica pendente e é decodificado de novo;
- os `not_implemented` do tipo viram `ok`, com linha na tabela nova;
- a API passa a servir `/api/telemetry/fs2/<tipo>/latest`, sem rota nova.

## 6. Documentar

Atualize a coluna "Decoder" da §3 em `docs/packet-spec-fs2.md` e a lista de tabelas em
`docs/schema-contract.md`.
