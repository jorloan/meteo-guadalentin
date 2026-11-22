import unittest
from datetime import datetime, timedelta, timezone

import imida_a_wu as m
from imida_descargar import parsear

ZONA = timezone(timedelta(hours=1))


def fila(fecha, tmed='20,0', prec='0,00', vv='2,00', vmax='5,00'):
    return {'fecha': fecha, 'tmed': tmed, 'hrmed': '40,5', 'radmed': '100,0', 'vvmed': vv,
            'vvmax': vmax, 'dvmed': '90,0', 'prec': prec, 'dewpt': '5,0'}


class Pruebas(unittest.TestCase):
    def test_num_y_fecha(self):
        self.assertEqual(m.num('0,0470420'), 0.047042)
        self.assertIsNone(m.num(''))
        self.assertEqual(m.inicio_fila('22/11/2026 15:00'), datetime(2026, 11, 22, 15, tzinfo=timezone.utc))
        self.assertIsNone(m.inicio_fila('x'))

    def test_nombre(self):
        self.assertEqual(m.nombre_legible('TOTANA (Lebor)'), 'Totana (Lebor)')
        self.assertEqual(m.nombre_legible('PUERTO LUMBRERAS (El Esparragal)'), 'Puerto Lumbreras (El Esparragal)')

    def test_convertir_ultima_hora(self):
        ahora = datetime(2026, 11, 22, 17, 30, tzinfo=ZONA)      # 16:30 UTC
        filas = [fila('22/11/2026 15:00'), fila('22/11/2026 14:00', tmed='25,0')]
        o = m.convertir('CA73', 'CARTAGENA (Los Belones)', 37.6, -0.9, filas, ZONA, ahora)
        self.assertEqual(o['stationID'], 'IM-CA73')
        self.assertEqual(o['metric']['temp'], 20.0)
        self.assertEqual(o['metric']['windSpeed'], 7.2)         # 2 m/s
        self.assertEqual(o['metric']['windGust'], 18.0)
        self.assertEqual(o['obsTimeLocal'], '2026-11-22 17:00:00')   # cierre 16:00 UTC

    def test_dato_viejo_se_ignora(self):
        ahora = datetime(2026, 11, 22, 21, 0, tzinfo=ZONA)
        self.assertIsNone(m.convertir('X', 'X', 1, 1, [fila('22/11/2026 15:00')], ZONA, ahora))
        self.assertIsNone(m.convertir('X', 'X', 1, 1, [], ZONA, ahora))
        self.assertIsNone(m.convertir('X', 'X', 1, 1, [fila('22/11/2026 15:00', tmed='')], ZONA, ahora))

    def test_lluvia_desde_medianoche_local(self):
        ahora = datetime(2026, 11, 22, 10, 30, tzinfo=ZONA)      # 09:30 UTC
        filas = [fila('22/11/2026 08:00', prec='1,5'),            # hoy
                 fila('22/11/2026 00:00', prec='0,5'),            # 01:00-02:00 local: hoy
                 fila('21/11/2026 22:00', prec='3,0'),            # 23:00-00:00 local: ayer
                 fila('21/11/2026 23:00', prec='0,2')]            # 00:00-01:00 local: hoy
        self.assertEqual(m.lluvia_hoy(filas, ahora), 2.2)
        self.assertIsNone(m.lluvia_hoy([], ahora))

    def test_parsear(self):
        celdas = ''.join(f'<td class="x">{v}</td>' for v in ['22/11/2026 15:00'] + ['1,0'] * 15)
        html = f'<table><tr onmouseover="a">{celdas}</tr></table>'
        f = parsear(html)
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]['fecha'], '22/11/2026 15:00')
        self.assertEqual(f[0]['dpv'], '1,0')


if __name__ == '__main__':
    unittest.main()
