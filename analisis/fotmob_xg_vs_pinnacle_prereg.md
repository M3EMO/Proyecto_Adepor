# Preregistro: xG de FotMob contra el cierre de Pinnacle (fijado 2026-10-22, antes de ver resultados)

Pregunta: el xG de FotMob agrega información sobre el cierre de Pinnacle sin margen en 1X2?

- Ligas: Premier (47), LaLiga (87), Bundesliga (54), Serie A (55), Ligue 1 (53).
- Entrenamiento: temporada 2024/25. Prueba: temporada 2025/26. Los coeficientes no se reajustan en la prueba.
- Base: probabilidades de PSCH/PSCD/PSCA (cierre Pinnacle) sin margen, método proporcional.
- Candidato: regresión logística multinomial (L2, C=1.0) con tres variables:
  log(pH/pD), log(pA/pD) y dxg = EMA(xG a favor - xG en contra) del local menos la del visita.
  EMA con alpha=0.1, calculada solo con partidos previos de la misma liga y temporada. Equipos con menos de 5 partidos previos: se excluye el partido de ambos modelos.
- Control: mismo candidato con goles en lugar de xG (dg). Mide si el xG aporta más que los goles.
- Métrica primaria: diferencia de log-loss (candidato - base) en la prueba, con bootstrap pareado por partido (10000 remuestreos, IC95).
- Éxito: el límite superior del IC95 es menor que 0. Cualquier otro resultado significa que no hay edge demostrado.
- No se cambia ninguna regla tras ver resultados. Los cambios se anotan como análisis exploratorio.
