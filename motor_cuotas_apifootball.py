# SHIM DE RETROCOMPATIBILIDAD — el codigo real vive en src/ingesta/motor_cuotas_apifootball.py.
# Capa secundaria: cubre ligas sudamericanas sin odds en The Odds API (motor_cuotas.py).
# Usa API-Football (api-sports.io) free tier: ventana +-1 dia, 100 req/dia.
from src.ingesta.motor_cuotas_apifootball import *  # noqa: F401,F403

if __name__ == "__main__":
    from src.ingesta.motor_cuotas_apifootball import main
    main()
