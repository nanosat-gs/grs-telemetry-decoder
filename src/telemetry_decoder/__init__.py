"""GRS Telemetry Decoder: o downlink do FloripaSat-2, de raw packet a telemetria."""

# Gravada em cada linha de decoded_frames. Subir esta versão faz o serviço
# tratar todo o histórico como pendente e decodificá-lo de novo, ao lado das
# linhas antigas (UNIQUE (raw_packet_id, decoder_version)). É assim que uma
# correção de layout chega aos pacotes que já estavam no banco.
DECODER_VERSION = "0.1.0"
