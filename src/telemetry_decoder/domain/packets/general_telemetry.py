"""General Telemetry (0x10): o retrato de saúde do satélite, a cada 60 s, pelo UHF.

Fonte do layout: `spacelab-ufsc/obdh2`, `firmware/app/tasks/general_telemetry.c`
(master em 2026-09-29), conferido com `doc/user_manual/packets.rst` e com a
spec da estação (`docs/packet-spec-fs2.md` §4). Offsets contados do início do
pacote — a coluna "Frame" da spec.

Dois layouts:

- **111 bytes** (`obdh2-111`): o firmware atual.
- **105 bytes** (`obdh2-105`): sem os três últimos campos. É o que o
  `spacelab-decoder` descreve (golds-ufsc.json). Não sabemos qual firmware
  voa, então o decoder aceita os dois; no de 105, os campos ausentes ficam
  NULL.

Sinal: `eps_battery_current` e `eps_battery_avg_current` são lidos como
**int16**. O firmware do OBDH2 guarda os dois num `uint16_t`
(`sl_eps2_current_t`) e a spec v0.1 diz uint16, mas o decoder de solo da
própria equipe do satélite os lê com sinal — a bateria carrega e descarrega.
Os bytes são os mesmos; se a interpretação estiver errada, o
`ngham_payload` guardado permite reprocessar. A confirmar com a equipe do EPS.
"""

from __future__ import annotations

from telemetry_decoder.domain.packets.base import Field, FixedLayoutDecoder
from telemetry_decoder.domain.satellite_enums import DownlinkId

FIELDS: tuple[Field, ...] = (
    # --- OBDH (spec §4.1) ---
    Field("obdh_timestamp", 8, "I", "s", "Tempo de sistema do satélite (Unix epoch)"),
    Field("obdh_mcu_temp", 12, "H", "K", "Temperatura do µC do OBDH"),
    Field("obdh_input_current", 14, "H", "mA", "Corrente de entrada do OBDH"),
    Field("obdh_input_voltage", 16, "H", "mV", "Tensão de entrada do OBDH"),
    Field("obdh_last_reset_cause", 18, "B", "", "Última causa de reset do OBDH"),
    Field("obdh_reset_counter", 19, "H", "", "Contador de reset do OBDH"),
    Field("obdh_last_valid_tc", 21, "B", "", "ID do último telecomando válido (UplinkId)"),
    # --- TTC, rádio de telemetria (§4.2) ---
    Field("ttc_radio_temp", 22, "H", "K", "Temperatura do rádio"),
    Field("ttc_last_tc_rssi", 24, "H", "", "RSSI do último TC válido (escala a confirmar)"),
    # --- Antena (§4.3) ---
    Field("antenna_temp", 26, "H", "K", "Temperatura da antena"),
    Field("antenna_status", 28, "H", "", "Status da antena ISIS (bitfield)"),
    # --- EPS (§4.4) ---
    Field("eps_mcu_temp", 30, "H", "K", "Temperatura do µC do EPS"),
    Field("eps_input_current", 32, "H", "mA", "Corrente do EPS e do µC do beacon"),
    Field("eps_last_reset_cause", 34, "B", "", "Última causa de reset do EPS"),
    Field("eps_reset_counter", 35, "H", "", "Contador de reset do EPS"),
    Field("eps_sp_voltage_my_px", 37, "H", "mV", "Tensão dos painéis -Y e +X"),
    Field("eps_sp_voltage_mx_pz", 39, "H", "mV", "Tensão dos painéis -X e +Z"),
    Field("eps_sp_voltage_mz_py", 41, "H", "mV", "Tensão dos painéis -Z e +Y"),
    Field("eps_sp_current_my", 43, "H", "mA", "Corrente do painel -Y"),
    Field("eps_sp_current_py", 45, "H", "mA", "Corrente do painel +Y"),
    Field("eps_sp_current_mx", 47, "H", "mA", "Corrente do painel -X"),
    Field("eps_sp_current_px", 49, "H", "mA", "Corrente do painel +X"),
    Field("eps_sp_current_mz", 51, "H", "mA", "Corrente do painel -Z"),
    Field("eps_sp_current_pz", 53, "H", "mA", "Corrente do painel +Z"),
    Field("eps_mppt_1_duty", 55, "B", "%", "Duty cycle do MPPT 1"),
    Field("eps_mppt_2_duty", 56, "B", "%", "Duty cycle do MPPT 2"),
    Field("eps_mppt_3_duty", 57, "B", "%", "Duty cycle do MPPT 3"),
    Field("eps_main_bus_voltage", 58, "H", "mV", "Tensão do barramento principal"),
    Field("eps_battery_voltage", 60, "H", "mV", "Tensão das baterias"),
    Field("eps_battery_current", 62, "h", "mA", "Corrente das baterias (com sinal)"),
    Field("eps_battery_avg_current", 64, "h", "mA", "Corrente média das baterias (com sinal)"),
    Field("eps_battery_acc_current", 66, "H", "mA", "Corrente acumulada (escala a confirmar)"),
    Field("eps_battery_monitor_temp", 68, "H", "K", "Temperatura do CI monitor de bateria"),
    Field("eps_heater_1_duty", 70, "B", "%", "Duty cycle do aquecedor de bateria 1"),
    Field("eps_heater_2_duty", 71, "B", "%", "Duty cycle do aquecedor de bateria 2"),
    # --- Estado de missão e posição (§4.5) ---
    Field("obdh_main_edc", 72, "B", "", "EDC principal"),
    Field("obdh_main_payload_state", 73, "B", "", "Payload principal ativo (PayloadId, 0 = inativo)"),
    Field("obdh_sec_payload_state", 74, "B", "", "Payload secundário ativo (PayloadId, 0 = inativo)"),
    Field("obdh_data_log_page", 75, "I", "", "Página do log de dados (relativa)"),
    Field("obdh_sbcd_page", 79, "I", "", "Página dos pacotes SBCD (relativa)"),
    Field("obdh_sensors_read_ts", 83, "I", "s", "Última leitura de sensores"),
    Field("obdh_position_ts", 87, "I", "s", "Instante da posição"),
    Field("obdh_latitude", 91, "h", "deg", "Latitude"),
    Field("obdh_longitude", 93, "h", "deg", "Longitude"),
    Field("obdh_altitude", 95, "h", "km", "Altitude"),
    Field("obdh_last_tle_update_ts", 97, "I", "s", "Última atualização de TLE"),
    Field("obdh_last_contact_ts", 101, "I", "s", "Último contato com o solo"),
    # --- Só no layout de 111 bytes ---
    Field("obdh_next_sched_tc_ts", 105, "I", "s", "Próximo telecomando agendado"),
    Field("obdh_tc_queue_size", 109, "B", "", "Tamanho da fila de telecomandos"),
    Field("obdh_mode", 110, "B", "", "Modo de operação do satélite"),
)

DECODER = FixedLayoutDecoder(
    pkt_id=DownlinkId.GENERAL_TELEMETRY,
    packet_type=DownlinkId.GENERAL_TELEMETRY.packet_type,
    table="fs2_general_telemetry",
    fields=FIELDS,
    layouts={111: "obdh2-111", 105: "obdh2-105"},
    sat_time_field="obdh_timestamp",
    source="obdh2 firmware/app/tasks/general_telemetry.c (master, 2026-09-29)",
)
