"""IDs de pacote e enums do FS-2 (spec §3, §5 e §6; `satellite.h` do OBDH2).

Os nomes dos tipos de downlink (`packet_type`) viram nome de tabela
(`fs2_<packet_type>`) e segmento de URL na API. Mudar um nome aqui é mudar o
contrato — ver docs/schema-contract.md.
"""

from __future__ import annotations

from enum import IntEnum


class DownlinkId(IntEnum):
    """Pacotes satélite -> solo."""

    # Fora da spec v0.1: o beacon sai do EPS2, não do OBDH, e por isso não está
    # no `packet_id_e`. ID e tamanho (65 B) vêm do `spacelab-decoder`
    # (golds-ufsc.json) e de um quadro real dele (tests/fixtures). Confirmar no
    # firmware do EPS2 antes de escrever o decoder.
    EPS_BEACON = 0x00
    MESSAGE_BROADCAST = 0x01
    PING_ANSWER = 0x02
    GENERAL_TELEMETRY = 0x10
    DATA_REQUEST_ANSWER = 0x11
    SUBSYSTEM_TABLE = 0x12
    TC_FEEDBACK = 0x13
    PARAM_VALUE = 0x14
    PACKET_BROADCAST = 0x15

    @property
    def packet_type(self) -> str:
        return self.name.lower()


class UplinkId(IntEnum):
    """Telecomandos solo -> satélite. Aparecem no downlink como o "último TC
    válido" do 0x10 e no TC Feedback."""

    PING_REQUEST = 0x40
    DATA_REQUEST = 0x41
    BROADCAST_MESSAGE = 0x42
    ENTER_HIBERNATION = 0x43
    LEAVE_HIBERNATION = 0x44
    ACTIVATE_MODULE = 0x45
    DEACTIVATE_MODULE = 0x46
    ACTIVATE_PAYLOAD = 0x47
    DEACTIVATE_PAYLOAD = 0x48
    ERASE_MEMORY = 0x49
    FORCE_RESET = 0x4A
    GET_SUBSYSTEM_TABLE = 0x4B
    SET_PARAMETER = 0x4C
    GET_PARAMETER = 0x4D
    TRANSMIT_PACKET = 0x4E
    UPDATE_TLE = 0x4F
    SCHEDULE_TC = 0x50


class SubsystemId(IntEnum):
    OBDH = 0
    TTC_1 = 1
    TTC_2 = 2
    EPS = 3


class DataId(IntEnum):
    """Argumento do Data Request (0x41); despacha o Data Request Answer (0x11)."""

    OBDH = 0
    EPS = 1
    TTC_0 = 2
    TTC_1 = 3
    ANT = 4
    SBCD_PKTS = 5
    PAYLOAD_INFO = 6


class TableId(IntEnum):
    """Argumento do Get Subsystem Table; despacha o Subsystem Table (0x12)."""

    OBDH = 0
    EPS = 1
    TTC_0 = 2
    TTC_1 = 3
    ANT = 4
    SBCD = 5
    EDC_0 = 6
    EDC_1 = 7
    PAYLOAD_X = 8


class PayloadId(IntEnum):
    """Também o valor dos campos "estado do payload" do 0x10 (0 = inativo)."""

    EDC_1 = 1
    EDC_2 = 2
    PAYLOAD_X = 3
    RADIATION_MONITOR = 4


class ModuleId(IntEnum):
    BATTERY_HEATER = 1
    BEACON = 2
    PERIODIC_TELEMETRY = 3


class MemoryId(IntEnum):
    NOR = 0
    FRAM = 1


class TcFeedbackCode(IntEnum):
    """Código do TC Feedback (0x13)."""

    SUCCESS = 0
    MISSION_MANAGER_TIMEOUT = -1
    SUBSYSTEM_COMM_FAILURE = -2
    DEVICE_COMM_FAILURE = -3
    FRAM_UPDATE_FAILURE = -4
    SCHEDULE_FAILURE = -5
