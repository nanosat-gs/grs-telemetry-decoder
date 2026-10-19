# FloripaSat-2 (GOLDS-UFSC) — Especificação de Pacotes e Regras de Comunicação

**Versão:** 0.2 · **Data:** 2026-10-06 · **Status:** em uso pelo `grs-telemetry-decoder`
**Escopo:** contrato de dados do enlace FS-2 para o serviço de decodificação da estação
terrena. O código do decoder cita as seções daqui.

**Histórico**

- **0.1 (2026-09-17)** — levantamento do firmware (`c:\dev\spacelab\Packet spec fs2.md`).
- **0.2 (2026-10-06)** — correções da implementação do decoder:
  - syncword no ar (§1);
  - RF resolvido (§1 e §8);
  - banda de cada rádio (§3);
  - pacote do beacon do EPS (§3);
  - layout legado de 105 bytes do `0x10` (§4);
  - sinal da corrente da bateria (§4.4).

## Proveniência

Levantado direto do firmware oficial (fonte de verdade), não de memória:

- `spacelab-ufsc/obdh2`:
  - `firmware/app/structs/satellite.h` (IDs de pacote e enums);
  - `firmware/app/tasks/general_telemetry.c` (layout do `0x10`, master de 2026-09-29);
  - `firmware/app/tasks/process_tc.c` (telecomandos e HMAC);
  - `firmware/app/libs/fsat_pkt/fsat_pkt.h` (estrutura do pacote);
  - `firmware/config/config.h` e `firmware/config/keys.h`;
  - structs de dados: `sl_eps2.h`, `sl_ttc2.h`, `isis_antenna.h`, `obdh_data.h`;
  - `doc/user_manual/packets.rst` (tabela oficial do `0x10`, que bate com o `.c`).
- `spacelab-ufsc/ttc2`:
  - `firmware/app/libs/ngham-1.0/*` (enlace);
  - `firmware/config/radio_0_config.h` e `radio_1_config.h` (PHY Si446x).
- `spacelab-ufsc/spacelab-decoder`: o decoder de solo da equipe do satélite
  (`data/satellites/golds-ufsc.json`, `tests/samples/golds-ufsc_beacon.wav`). Serve como
  conferência. Onde ele diverge do firmware, o firmware vale, e a divergência fica
  registrada.

---

## 1. Pilha de comunicação

| Camada | Implementação FS-2 | Notas |
|---|---|---|
| **Física (PHY)** | Transceptor **Si446x**, **2GFSK** (`MODEM_MOD_TYPE = 0x03`) | Dois rádios (§3). Beacon: 145,9 MHz, 1200 baud. Dados: 468,4 MHz, 4800 baud. |
| **Enlace (NGHam)** | Lib `ngham-1.0` embarcada no TTC2; no solo, **PyNGHam** 1.1.1 | Preâmbulo `0xAA`; syncword **`5D E6 2A 7E`** (no ar); size tag 3 B; scrambler CCSDS; Reed-Solomon (codeword máx. 255 B); CRC-16; **payload máx. 220 B**. |
| **Aplicação (FSat packet)** | `fsat_pkt` | Cabeçalho comum a todos os pacotes (§2). |

Caminho: `IQ → 2GFSK → NGHam → FSat packet`. O FS-2 usa NGHam nos **dois** rádios. O FS-1
também mandava AX.25 no mesmo syncword.

**Syncword: duas formas, um valor.**

- **`5D E6 2A 7E`** é o que vai no ar, em MSB primeiro. É o `NGH_SYNC` do `ngham.c` e o que
  o detector da estação procura.
- **`BA 67 54 7E`** é o mesmo vetor com os bits de cada byte invertidos: a forma do
  registrador do Si446x, que transmite LSB primeiro. Procurar esta forma no fluxo
  demodulado acha **zero** pacotes.
- Isso foi medido contra um beacon real do FS-1 e está congelado em
  `grs-station/tests/test_rx_real_signal.py`.

**Tamanho do quadro no ar:** o maior quadro NGHam depois do syncword tem 3 B de size tag
\+ 255 B de codeword = **258 B**. É o tamanho da fatia que o detector da estação publica
(`GRS_SYNCWORD_PACKET_BYTES`).

---

## 2. Estrutura do pacote de aplicação (FSat packet)

Todos os pacotes, de downlink e de uplink, têm o mesmo cabeçalho. Fonte: `fsat_pkt.h`.

| Campo | Offset | Tamanho | Tipo | Descrição |
|---|---|---|---|---|
| `id` | 0 | 1 B | `uint8` | ID do pacote (§3 e §5) |
| `callsign` | 1 | 7 B | `char[7]` | Indicativo. Downlink: fonte (`" PY0EFS"`). Uplink: requisitante. Padding com espaço à esquerda. |
| `payload` | 8 | ≤ 212 B | bytes | Dados específicos do pacote |

- **Endianness:** todos os campos multibyte são **big-endian** (MSB primeiro).
- **`callsign` do FS-2:** `" PY0EFS"`, 7 caracteres com espaço à esquerda
  (`CONFIG_SATELLITE_CALLSIGN`). O FS-1 completava com `'0'` (`"0PY0EFS"`).
- No `spacelab-decoder`, esta camada aparece como `protocol_network: "SLP"`. Não há mais
  nada entre o NGHam e este cabeçalho.

---

## 3. Pacotes de downlink (satélite → solo)

`packet_id_e` do OBDH2, `0x01`–`0x15`, e o beacon do EPS.

| ID | Nome (`packet_type`) | Rádio | Conteúdo | Decoder |
|---|---|---|---|---|
| `0x00` | EPS Beacon (`eps_beacon`) | VHF (beacon) | Beacon do EPS2: **65 B** | — |
| `0x01` | Message Broadcast (`message_broadcast`) | — | Mensagem repassada | — |
| `0x02` | Ping Answer (`ping_answer`) | `TTC_1` = VHF | Ecoa os 7 bytes do ping: **15 B** | **sim** |
| `0x10` | **General Telemetry** (`general_telemetry`) | `TTC_0` = UHF | Saúde do satélite: **111 B** (§4) | **sim** |
| `0x11` | Data Request Answer (`data_request_answer`) | `TTC_0` = UHF | Página de memória (por `data_id`) | — |
| `0x12` | Subsystem Table (`subsystem_table`) | — | Tabela de um subsistema (por `table_id`) | — |
| `0x13` | TC Feedback (`tc_feedback`) | `TTC_0` = UHF | Quem pediu, ID do TC, relógio, erro `int16`: **22 B** (§6) | **sim** |
| `0x14` | Param Value (`param_value`) | — | Valor de um parâmetro | — |
| `0x15` | Packet Broadcast (`packet_broadcast`) | — | Pacote repassado | — |

- **`0x00` não está no `packet_id_e`.** O beacon sai do EPS2, não do OBDH. ID e tamanho vêm
  do `spacelab-decoder` e de um quadro real dele (fixture do decoder: RS limpo, callsign
  `" PY0EFS"`). Falta levantar o layout no firmware do EPS2 antes de escrever o decoder.
- **Rádios:** `TTC_0` = UHF de dados (468,4 MHz, 4800 baud); `TTC_1` = VHF de beacon
  (145,9 MHz, 1200 baud).
  - O firmware manda o `0x10` pelo `TTC_0`, e o `spacelab-decoder` põe o `0x10` e o
    `0x11` no `downlink_uhf`, e o `0x00` e o `0x02` no `downlink_vhf`.
  - O decoder usa isso para marcar `radio_mismatch`, um aviso que não impede a decodificação.
  - "—": o rádio desse tipo não está documentado.
- **Nomes do `spacelab-decoder`:** em alguns IDs, os nomes de lá diferem dos daqui. Por
  exemplo, ele chama o `0x12` de "Payload data". Os nomes daqui são os do `packet_id_e` do
  firmware.

---

## 4. General Telemetry `0x10` — layout byte a byte

**Tamanho total:** 1 (ID) + 7 (callsign) + **103 (payload)** = **111 bytes**.
Período nominal: **60 s**, fora de hibernação e com `general_telemetry_on`.
Fonte: `general_telemetry.c`. **PL** = offset dentro do payload; **Frame** = PL + 8, que é o
offset usado pelo decoder.

Todos os inteiros são **big-endian**. Temperaturas em **K**, tensões em **mV**, correntes
em **mA**.

**Layout legado de 105 bytes.** O `spacelab-decoder` descreve o `0x10` sem os três últimos
campos (Frame 105–110). Não sabemos qual firmware voa. Por isso o decoder aceita os dois
comprimentos:

- `obdh2-111`: o atual;
- `obdh2-105`: o legado, em que os três campos ficam nulos.

Qualquer outro comprimento é registrado como `layout_mismatch`.

### 4.1 OBDH

| PL | Frame | Campo | Tipo | Unidade | Nota |
|---|---|---|---|---|---|
| 0–3 | 8–11 | Timestamp (tempo de sistema) | `uint32` | s | Relógio do satélite, Unix epoch |
| 4–5 | 12–13 | Temperatura do µC OBDH | `uint16` | K | °C = K − 273,15 |
| 6–7 | 14–15 | Corrente de entrada OBDH | `uint16` | mA | |
| 8–9 | 16–17 | Tensão de entrada OBDH | `uint16` | mV | |
| 10 | 18 | Última causa de reset OBDH | `uint8` | código | |
| 11–12 | 19–20 | Contador de reset OBDH | `uint16` | — | |
| 13 | 21 | Último TC válido | `uint8` | ID | ID do pacote de uplink (§5) |

### 4.2 TTC (rádio de telemetria)

| PL | Frame | Campo | Tipo | Unidade | Nota |
|---|---|---|---|---|---|
| 14–15 | 22–23 | Temperatura do rádio | `uint16` | K | |
| 16–17 | 24–25 | RSSI do último TC válido | `uint16` | — | Escala a confirmar (TTC2) |

### 4.3 Antena

| PL | Frame | Campo | Tipo | Unidade | Nota |
|---|---|---|---|---|---|
| 18–19 | 26–27 | Temperatura da antena | `uint16` | K | |
| 20–21 | 28–29 | Status da antena (`code`) | `uint16` | bitfield | Status ISIS |

### 4.4 EPS

| PL | Frame | Campo | Tipo | Unidade | Nota |
|---|---|---|---|---|---|
| 22–23 | 30–31 | Temperatura do µC EPS | `uint16` | K | |
| 24–25 | 32–33 | Corrente de entrada EPS | `uint16` | mA | EPS + µC do beacon |
| 26 | 34 | Última causa de reset EPS | `uint8` | código | |
| 27–28 | 35–36 | Contador de reset EPS | `uint16` | — | |
| 29–30 | 37–38 | Tensão painel solar −Y+X | `uint16` | mV | |
| 31–32 | 39–40 | Tensão painel solar −X+Z | `uint16` | mV | |
| 33–34 | 41–42 | Tensão painel solar −Z+Y | `uint16` | mV | |
| 35–36 | 43–44 | Corrente painel solar −Y | `uint16` | mA | |
| 37–38 | 45–46 | Corrente painel solar +Y | `uint16` | mA | |
| 39–40 | 47–48 | Corrente painel solar −X | `uint16` | mA | |
| 41–42 | 49–50 | Corrente painel solar +X | `uint16` | mA | |
| 43–44 | 51–52 | Corrente painel solar −Z | `uint16` | mA | |
| 45–46 | 53–54 | Corrente painel solar +Z | `uint16` | mA | |
| 47 | 55 | MPPT 1 duty cycle | `uint8` | % | |
| 48 | 56 | MPPT 2 duty cycle | `uint8` | % | |
| 49 | 57 | MPPT 3 duty cycle | `uint8` | % | |
| 50–51 | 58–59 | Tensão do barramento principal | `uint16` | mV | |
| 52–53 | 60–61 | Tensão da bateria | `uint16` | mV | |
| 54–55 | 62–63 | Corrente da bateria | **`int16`** | mA | **Com sinal** (ver abaixo) |
| 56–57 | 64–65 | Corrente média da bateria | **`int16`** | mA | **Com sinal** |
| 58–59 | 66–67 | Corrente acumulada da bateria | `uint16` | mA·? | Escala a confirmar (EPS2) |
| 60–61 | 68–69 | Temperatura do monitor de bateria | `uint16` | K | |
| 62 | 70 | Battery heater 1 duty cycle | `uint8` | % | |
| 63 | 71 | Battery heater 2 duty cycle | `uint8` | % | |

**Sinal da corrente da bateria.**

- O OBDH2 guarda as duas correntes num `uint16_t` (`sl_eps2_current_t`), e a v0.1 desta
  spec dizia `uint16`.
- O decoder de solo da equipe do satélite lê as duas como `int16`, e fisicamente faz
  sentido: a bateria carrega e descarrega.
- Os bytes são os mesmos nos dois casos. O decoder segue o `int16`. Se estiver errado, o
  payload guardado permite reprocessar.
- **A confirmar com a equipe do EPS.**

### 4.5 Estado de missão e posição (OBDH)

| PL | Frame | Campo | Tipo | Unidade | Nota |
|---|---|---|---|---|---|
| 64 | 72 | EDC principal | `uint8` | ID | |
| 65 | 73 | Estado do payload principal | `uint8` | PL_ID | `0` = inativo (§6) |
| 66 | 74 | Estado do payload secundário | `uint8` | PL_ID | `0` = inativo |
| 67–70 | 75–78 | Página do log de dados OBDH | `uint32` | página | Relativa |
| 71–74 | 79–82 | Página de pacotes SBCD | `uint32` | página | Relativa |
| 75–78 | 83–86 | Timestamp da última leitura de sensores | `uint32` | s | |
| 79–82 | 87–90 | Timestamp da posição | `uint32` | s | |
| 83–84 | 91–92 | Latitude | `int16` | grau | **Com sinal** |
| 85–86 | 93–94 | Longitude | `int16` | grau | **Com sinal** |
| 87–88 | 95–96 | Altitude | `int16` | km | **Com sinal** |
| 89–92 | 97–100 | Timestamp da última atualização de TLE | `uint32` | s | |
| 93–96 | 101–104 | Timestamp do último contato | `uint32` | s | Fim do layout legado (105 B) |
| 97–100 | 105–108 | Timestamp do próximo TC agendado | `uint32` | s | Só no layout de 111 B |
| 101 | 109 | Tamanho da fila de TC | `uint8` | — | Só no layout de 111 B |
| 102 | 110 | Modo de operação | `uint8` | código | Só no layout de 111 B |

Timestamp `0` significa "nunca aconteceu" (último contato, próximo TC), e não 1970.

---

## 5. Telecomandos de uplink (solo → satélite)

`packet_id_e`, faixa `0x40`–`0x50`. Formato geral:
`ID(1) + callsign(7) + argumentos + [HMAC(20)]`.

- HMAC = HMAC-SHA1, **20 bytes**, sempre no final.
- Calculado sobre `ID + callsign + argumentos`, sem a própria tag.

| ID | Telecomando | Argumentos (após callsign) | Autenticação (bytes cobertos pelo HMAC) |
|---|---|---|---|
| `0x40` | Ping Request | 7 B (ecoados no pong) | **Nenhuma** (aberto ham) |
| `0x41` | Data Request | `data_id(1)` + `start_idx(4)` + `end_idx(4)` | HMAC (17) |
| `0x42` | Broadcast Message | mensagem | — |
| `0x43` | Enter Hibernation | `horas(2)` | HMAC (10) |
| `0x44` | Leave Hibernation | — | HMAC |
| `0x45` | Activate Module | `module_id(1)` | HMAC |
| `0x46` | Deactivate Module | `module_id(1)` | HMAC |
| `0x47` | Activate Payload | `payload_id(1)` | HMAC (9) |
| `0x48` | Deactivate Payload | `payload_id(1)` | HMAC (9) |
| `0x49` | Erase Memory | — | HMAC |
| `0x4A` | Force Reset | — | HMAC |
| `0x4B` | Get Subsystem Table | `table_id(1)` | HMAC |
| `0x4C` | Set Parameter | `subsystem_id(1)` + `param_id(1)` + `valor(4)` | HMAC (14) |
| `0x4D` | Get Parameter | `subsystem_id(1)` + `param_id(1)` | HMAC |
| `0x4E` | Transmit Packet | mensagem (quadro total ≤ 73 B) | HMAC (`pkt_len − 20`) |
| `0x4F` | Update TLE | `linha_TLE(50)` | HMAC (58) |
| `0x50` | Schedule TC | TC a agendar | HMAC |

**Regras de autenticação:**

- Cada telecomando tem sua **própria chave de 16 bytes**: são 16 chaves distintas em
  `config/keys.h`, não reproduzidas aqui.
- Activate/Deactivate Payload usam chaves distintas por payload (EDC vs. Payload-X).
- O **ping é aberto** (sem HMAC), herança ham.
- TCs **agendados** não são reautenticados na execução: foram autenticados ao entrar na
  fila.

---

## 6. Enums auxiliares

Fonte: `satellite.h`. No decoder: `domain/satellite_enums.py`.

- **Subsystem IDs:** `OBDH=0`, `TTC_1=1`, `TTC_2=2`, `EPS=3`
- **Data IDs** (Data Request `0x41`): `OBDH=0`, `EPS=1`, `TTC_0=2`, `TTC_1=3`, `ANT=4`,
  `SBCD_PKTS=5`, `PAYLOAD_INFO=6`
- **Table IDs** (Get Subsystem Table): `OBDH=0`, `EPS=1`, `TTC_0=2`, `TTC_1=3`, `ANT=4`,
  `SBCD=5`, `EDC_0=6`, `EDC_1=7`, `PAYLOAD_X=8`
- **Payload IDs:** `EDC_1=1`, `EDC_2=2`, `PAYLOAD_X=3`, `RADIATION_MONITOR=4`
- **Module IDs:** `BATTERY_HEATER=1`, `BEACON=2`, `PERIODIC_TELEMETRY=3`
- **Memory IDs:** `NOR=0`, `FRAM=1`
- **Feedback error codes** (`0x13`):
  - `0` = sucesso;
  - `−1` = timeout do mission manager;
  - `−2` = falha de comunicação com o subsistema;
  - `−3` = falha de comunicação com o device;
  - `−4` = falha ao atualizar a FRAM;
  - `−5` = falha ao agendar o TC.

---

## 7. Tipos de dados (resumo)

Os valores já vêm em unidades de engenharia, não como ADC cru. O decoder grava o inteiro
como veio, e a API converte na leitura.

| Grandeza | Tipo | Sinal | Unidade | Conversão |
|---|---|---|---|---|
| Temperaturas | `uint16` | sem | K | °C = valor − 273,15 |
| Tensões | `uint16` | sem | mV | V = valor / 1000 |
| Correntes (entradas, painéis) | `uint16` | sem | mA | — |
| Correntes da bateria (atual, média) | `int16` | **com** | mA | — |
| Duty cycles | `uint8` | sem | % | 0–100 |
| Contadores / causas de reset | `uint16` / `uint8` | sem | — | — |
| RSSI | `uint16` | sem | — | escala a confirmar |
| Timestamps | `uint32` | sem | s | Unix epoch; `0` = nunca |
| Latitude / Longitude / Altitude | `int16` | **com** | grau / km | — |
| Páginas de memória | `uint32` | sem | página | relativa à página inicial |
| Status da antena | `uint16` | sem | bitfield | — |
| Estados / modo / fila | `uint8` | sem | código | enums da §6 |

**Persistência:** ver `schema-contract.md`.

- O cru imutável é o `raw_packets` do archiver.
- Os dois timestamps são o `received_at` (estação) e o `sat_time` (satélite).
- O `0x10` não carrega a versão de firmware.

---

## 8. Pendências

**Resolvido desde a v0.1:** frequência e baud dos dois rádios. Ver
`grs-station/docs/rx-datapath.md`, "Dois rádios", com valores do
`ttc2/firmware/config/radio_*_config.h` e da coordenação IARU.

**Em aberto:**

1. **Qual firmware do OBDH voa**: `0x10` de 111 ou de 105 bytes. O decoder aceita os dois.
2. **Sinal da corrente da bateria** (§4.4): `int16`, como o decoder da equipe, ou `uint16`,
   como o tipo do firmware.
3. **Escala do RSSI** e da **corrente acumulada** da bateria.
4. **Layout do beacon do EPS2** (`0x00`), o pacote que mais vamos receber.
5. **Rádio de cada tipo** marcado "—" no §3.

*Regra do documento: tudo aqui é derivado do firmware oficial. Onde o decoder de solo da
equipe diverge, a divergência está escrita e a escolha do decoder, justificada.*
