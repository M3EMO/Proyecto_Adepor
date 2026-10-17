import random

from scripts.drift_detector import umbral_drift


def test_umbral_usa_error_estandar_de_la_media():
    rng = random.Random(3)
    hist = [rng.choice((0.1, 0.5, 1.3)) for _ in range(400)]   # Brier por partido, SD ~0.5
    ventana = hist[:30]
    base, umbral, critico = umbral_drift(hist, ventana)
    # SE ~ sqrt(0.25/30 + 0.25/400) ~ 0.095 -> umbral ~ base + 0.19, no base + 0.04
    assert 0.15 < umbral - base < 0.25 and critico > umbral


def test_detect_drift_db_nueva_no_falla(db):
    from scripts.drift_detector import detect_drift
    detect_drift(dry_run=True)
