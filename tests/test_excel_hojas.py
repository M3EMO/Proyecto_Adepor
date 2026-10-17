"""Hojas Excel: el dinero solo cuenta partidos liquidados."""
from openpyxl import Workbook

from src.persistencia.excel_hoja_backtest import poblar_backtest


def _row(id_p, ap, estado, gl=2, gv=0, stake=100.0):
    return (id_p, '2026-05-01 20:00', 'A', 'B', 'Argentina',
            0.5, 0.25, 0.25, 0.5, 0.5,
            ap, '', stake, 0.0,
            2.0, 3.4, 3.8, 1.9, 1.9,
            estado, gl, gv, 0.1, 'NO', '', 0.0)


def test_resumen_excluye_filas_no_liquidadas():
    wb = Workbook()
    stats = poblar_backtest(wb, [_row('liq', '[GANADA] LOCAL', 'Liquidado'),
                                 _row('calc', '[APOSTAR] LOCAL', 'Calculado')], 100000)
    s = stats['Argentina']
    assert s['apuestas'] == 1 and s['vol'] == 100.0 and s['pl'] == 100.0
