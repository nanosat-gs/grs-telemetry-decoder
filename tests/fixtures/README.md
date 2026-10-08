# Fixtures do decodificador

`real_frames.json`: raw packets que vieram **do ar**, como o detector da estação os
publicaria (os bytes depois do syncword `5D E6 2A 7E`). Gerado por
`tools/extract_ngham_slices.py`, que passa o WAV pela recuperação de tempo da estação
(o M&M do `grs-demodulator`) e corta a fatia depois de cada syncword.

Os quadros sintéticos de `tests/frames.py` saem do `PyNGHam.encode()` e voltam pelo
`PyNGHam.decode()`. Se os dois concordarem num erro, o teste fica verde. Foi assim que o
syncword invertido passou pela fatia RX. Estes quadros reais não têm essa fraqueza.

## `fs1_beacon`: FloripaSat-1, do ar

| | |
|---|---|
| Origem | `grs-station/tests/fixtures/floripasat1-beacon-1200.wav` |
| Gravação | radioamador **DK3WN** (JN49lr), **2019-12-20 09:51 UTC**, repositório [floripasat/received-data](https://github.com/floripasat/received-data) |
| Enlace | beacon VHF, 145,9 MHz, 1200 baud |
| Conteúdo | 2 quadros NGHam (pacote EPS, `0x01`, 39 bytes) e 1 quadro AX.25, que serve de negativo |
| Oráculo | primeira linha do `data/beacon.csv` daquele repositório: a telemetria que o decoder **oficial** do SpaceLab tirou da mesma passagem |

**O que provam:**

- ordem de bit, size tag, descrambler CCSDS e CRC contra dado do ar;
- conferidos campo a campo contra uma decodificação independente (bateria, temperatura,
  corrente e carga da linha das 09:51:22).

**O achado congelado:** nos dois quadros, dados, cabeçalho, CRC e padding batem byte a byte
com o que o PyNGHam codificaria. **Só os 16 bytes de paridade Reed-Solomon diferem.**

- O RS não valida (`rs_errors = -1`), mas o CRC passa, e o pacote é aceito.
- O FS-2 não tem isso (próxima fixture).
- Hipóteses descartadas: paridade sem scrambler, paridade invertida, e outros `fcr`/`prim`
  de RS.

## `golds_ufsc_beacon`: FS-2 (GOLDS-UFSC)

| | |
|---|---|
| Origem | `spacelab-ufsc/spacelab-decoder`, `tests/samples/golds-ufsc_beacon.wav` (GPL-3.0) |
| Enlace | beacon VHF, 1200 baud |
| Conteúdo | 1 quadro NGHam: pacote `0x00` (beacon do EPS), 65 bytes, callsign `" PY0EFS"` |

**O que prova:** o Reed-Solomon do PyNGHam é o mesmo do FS-2 (0 correções). É o único
quadro do satélite que temos.

O `0x00` ainda não tem decoder, então esta fixture também exercita o caminho
`not_implemented` com um pacote real.

## Refazer

```bash
python tools/extract_ngham_slices.py ../../tests/fixtures/floripasat1-beacon-1200.wav --baud 1200
python tools/extract_ngham_slices.py golds-ufsc_beacon.wav --baud 1200
```

O comando exige o `grs-demodulator` instalado, que vem com o `bootstrap.ps1 -Dev` do
`grs-station`.

**Offsets.** A ferramenta acha os quadros do FS-1 nos bits 1068 e 7132. Os 1036 e 7100 do
`test_rx_real_signal.py` são o início do syncword, 32 bits antes.
