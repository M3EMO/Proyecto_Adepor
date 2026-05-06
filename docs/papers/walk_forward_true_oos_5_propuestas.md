# Walk-Forward TRUE-OOS — 5 Propuestas (sesion 2026-05-02_team_filtros_oro)
Fecha: 2026-05-02T16:05:40.039771
## Universo
- Matched: **8892** stats+cuotas (s.fecha_fdco JOIN)
- Por liga: {'Brasil': 1209, 'Argentina': 1217, 'Alemania': 927, 'Francia': 1002, 'Inglaterra': 1169, 'Turquia': 1065, 'Espana': 1155, 'Italia': 1148}
- Por year: {2022: 1660, 2023: 3014, 2024: 2838, 2025: 1123, 2026: 257}

## Splits walk-forward
- TRAIN pool (year<=2024): 3089 picks (argmax V0, EV>=1.03)
- VALIDATION 2025: 620 picks
- HOLDOUT 2026 (CONGELADO): 167 picks
- Bonferroni alpha = 0.0100 (= 0.05/5)

## Tabla resumen
| Propuesta | N_IS | Yield_IS | CI95 | p5_boot | N_2026 | Y_2026 | Anos+ | Veredicto |
|---|---|---|---|---|---|---|---|---|
| P1_Italia | 166 | -0.004 | [-0.164,+0.152] | -0.140 | 4 | -0.230 | 1/3 | **RECHAZAR** |
| P2_Espana | 187 | -0.037 | [-0.199,+0.129] | -0.169 | 8 | +0.121 | 2/3 | **RECHAZAR** |
| P3_Italia_Espana | 353 | -0.021 | [-0.132,+0.090] | -0.113 | 12 | +0.004 | 2/3 | **RECHAZAR** |
| P4_Whitelist | 123 | -0.087 | [-0.285,+0.109] | -0.253 | 5 | -0.666 | 1/3 | **RECHAZAR** |
| P5_Blacklist | 3587 | -0.041 | [-0.086,+0.004] | -0.078 | 167 | +0.020 | 1/3 | **RECHAZAR** |

### P1_Italia — Italia V0 P>=0.55 + div>=0.05
- IS pooled: N=166, yield=-0.0036, hit=0.518, CI95=[-0.1645,+0.1522], boot_p5=-0.1397, sharpe=-0.046, maxdd=-12.82
- Holdout 2026: N=4, yield=-0.2300, hit=0.500, CI95=[-1.0000,+0.5400]
- Por year:
  - 2023: N=61 y=-0.071 hit=0.508 CI95=[-0.308,+0.186]
  - 2024: N=65 y=+0.082 hit=0.523 CI95=[-0.194,+0.343]
  - 2025: N=40 y=-0.041 hit=0.525 CI95=[-0.333,+0.262]
  - 2026: N=4 y=-0.230 hit=0.500 CI95=[-1.000,+0.540]
- Por liga (IS pooled):
  - Italia: N=166 y=-0.004 hit=0.518
- Criterios promocion: {'n_is>=100': True, 'yield_is>=0.05': False, 'boot_p5>0': False, 'anos_pos>=2/3': False, 'anos_pos': '1/3'}
- **Veredicto: RECHAZAR**
- Veto: ['one-shot (1/N+ anos positivos)']

### P2_Espana — Espana V0 P>=0.55 + div>=0.05
- IS pooled: N=187, yield=-0.0368, hit=0.444, CI95=[-0.1991,+0.1291], boot_p5=-0.1694, sharpe=-0.434, maxdd=-25.20
- Holdout 2026: N=8, yield=+0.1213, hit=0.500, CI95=[-0.7250,+0.9375]
- Por year:
  - 2023: N=64 y=-0.258 hit=0.344 CI95=[-0.510,+0.010]
  - 2024: N=81 y=+0.098 hit=0.519 CI95=[-0.142,+0.339]
  - 2025: N=42 y=+0.041 hit=0.452 CI95=[-0.321,+0.436]
  - 2026: N=8 y=+0.121 hit=0.500 CI95=[-0.625,+0.968]
- Por liga (IS pooled):
  - Espana: N=187 y=-0.037 hit=0.444
- Criterios promocion: {'n_is>=100': True, 'yield_is>=0.05': False, 'boot_p5>0': False, 'anos_pos>=2/3': True, 'anos_pos': '2/3'}
- **Veredicto: RECHAZAR**

### P3_Italia_Espana — P1 + P2 combinadas
- IS pooled: N=353, yield=-0.0212, hit=0.479, CI95=[-0.1319,+0.0902], boot_p5=-0.1127, sharpe=-0.364, maxdd=-29.78
- Holdout 2026: N=12, yield=+0.0042, hit=0.500, CI95=[-0.5667,+0.6126]
- Por year:
  - 2023: N=125 y=-0.167 hit=0.424 CI95=[-0.335,+0.010]
  - 2024: N=146 y=+0.091 hit=0.521 CI95=[-0.083,+0.267]
  - 2025: N=82 y=+0.001 hit=0.488 CI95=[-0.235,+0.255]
  - 2026: N=12 y=+0.004 hit=0.500 CI95=[-0.567,+0.613]
- Por liga (IS pooled):
  - Italia: N=166 y=-0.004 hit=0.518
  - Espana: N=187 y=-0.037 hit=0.444
- Criterios promocion: {'n_is>=100': True, 'yield_is>=0.05': False, 'boot_p5>0': False, 'anos_pos>=2/3': True, 'anos_pos': '2/3'}
- **Veredicto: RECHAZAR**

### P4_Whitelist — Whitelist top-yield N=6
- IS pooled: N=123, yield=-0.0868, hit=0.423, CI95=[-0.2852,+0.1086], boot_p5=-0.2533, sharpe=-0.857, maxdd=-32.11
- Holdout 2026: N=5, yield=-0.6660, hit=0.200, CI95=[-1.0000,+0.0020]
- Por year:
  - 2023: N=62 y=-0.186 hit=0.371 CI95=[-0.471,+0.101]
  - 2024: N=48 y=-0.109 hit=0.417 CI95=[-0.416,+0.198]
  - 2025: N=13 y=+0.472 hit=0.692 CI95=[-0.100,+1.002]
  - 2026: N=5 y=-0.666 hit=0.200 CI95=[-1.000,+0.002]
- Por liga (IS pooled):
  - Inglaterra: N=55 y=-0.081 hit=0.418
  - Italia: N=68 y=-0.091 hit=0.426
- Por equipo (top por N, IS pooled):
  - fiorentina: N=36 y=-0.231 hit=0.361
  - atalanta: N=32 y=+0.065 hit=0.500
  - astonvilla: N=28 y=+0.202 hit=0.536
  - newcastle: N=27 y=-0.375 hit=0.296
- Criterios promocion: {'n_is>=100': True, 'yield_is>=0.05': False, 'boot_p5>0': False, 'anos_pos>=2/3': False, 'anos_pos': '1/3'}
- **Veredicto: RECHAZAR**
- Veto: ['one-shot (1/N+ anos positivos)']

### P5_Blacklist — Excluir blacklist bottom N=7
- IS pooled: N=3587, yield=-0.0411, hit=0.370, CI95=[-0.0863,+0.0038], boot_p5=-0.0781, sharpe=-1.769, maxdd=-223.84
- Holdout 2026: N=167, yield=+0.0199, hit=0.383, CI95=[-0.1849,+0.2259]
- Por year:
  - 2023: N=1486 y=-0.047 hit=0.359 CI95=[-0.118,+0.026]
  - 2024: N=1497 y=-0.083 hit=0.356 CI95=[-0.152,-0.013]
  - 2025: N=604 y=+0.078 hit=0.434 CI95=[-0.033,+0.189]
  - 2026: N=167 y=+0.020 hit=0.383 CI95=[-0.184,+0.227]
- Por liga (IS pooled):
  - Inglaterra: N=535 y=+0.072 hit=0.437
  - Francia: N=453 y=+0.072 hit=0.417
  - Espana: N=539 y=-0.009 hit=0.375
  - Turquia: N=202 y=-0.044 hit=0.376
  - Brasil: N=483 y=-0.068 hit=0.315
  - Italia: N=481 y=-0.073 hit=0.380
  - Alemania: N=442 y=-0.098 hit=0.391
  - Argentina: N=452 y=-0.206 hit=0.263
- Por equipo (top por N, IS pooled):
  - bologna: N=49 y=+0.063 hit=0.429
  - brighton: N=46 y=-0.064 hit=0.391
  - vallecano: N=46 y=-0.104 hit=0.283
  - nice: N=44 y=-0.014 hit=0.386
  - celta: N=43 y=-0.294 hit=0.279
  - athbilbao: N=43 y=+0.011 hit=0.419
  - stuttgart: N=42 y=+0.150 hit=0.500
  - toulouse: N=42 y=+0.250 hit=0.429
  - rennes: N=41 y=-0.101 hit=0.415
  - crystalpalace: N=41 y=+0.136 hit=0.415
  - brest: N=40 y=+0.376 hit=0.500
  - lille: N=39 y=-0.289 hit=0.308
  - girona: N=36 y=+0.336 hit=0.500
  - fiorentina: N=36 y=-0.231 hit=0.361
  - m'gladbach: N=36 y=-0.249 hit=0.306
- Criterios promocion: {'n_is>=100': True, 'yield_is>=0.05': False, 'boot_p5>0': False, 'anos_pos>=2/3': False, 'anos_pos': '1/3'}
- **Veredicto: RECHAZAR**
- Veto: ['one-shot (1/N+ anos positivos)']
