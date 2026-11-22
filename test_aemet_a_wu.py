import unittest
from datetime import datetime, timedelta, timezone

import aemet_a_wu as a
from aemet_descargar import agrupar

ZONA = timezone(timedelta(hours=1))


def fila(fint, ta='15,0', prec='0.0', vv='2.0', vmax='5.0'):
    return {'fint': fint, 'ta': ta, 'hr': '60', 'vv': vv, 'vmax': vmax, 'dv': '90', 'pres': '1005.2',
            'prec': prec, 'tpr': '8.0'}


EST = {'ubi': 'MURCIA/ALCANTARILLA', 'lat': 37.96, 'lon': -1.23, 'alt': 80}


class Pruebas(unittest.TestCase):
    def test_nombre_y_num(self):
        self.assertEqual(a.nombre_legible('MURCIA/ALCANTARILLA'), 'Murcia/Alcantarilla')
        self.assertEqual(a.nombre_legible('AGUILAS'), 'Aguilas')
        self.assertEqual(a.num('1,5'), 1.5)
        self.assertIsNone(a.num(None))

    def test_convertir_ultima_fila(self):
        ahora = datetime(2026, 11, 22, 21, 30, tzinfo=ZONA)          # 20:30 UTC
        e = dict(EST, filas=[fila('2026-11-22T20:20:00', ta='12,5'), fila('2026-11-22T20:10:00', ta='13')])
        o = a.convertir('7228', e, ZONA, ahora)
        self.assertEqual(o['stationID'], 'AE-7228')
        self.assertEqual(o['metric']['temp'], 12.5)
        self.assertEqual(o['metric']['windSpeed'], 7.2)
        self.assertEqual(o['metric']['windGust'], 18.0)
        self.assertEqual(o['metric']['pressure'], 1005.2)
        self.assertEqual(o['obsTimeLocal'], '2026-11-22 21:20:00')

    def test_viejo_o_vacio(self):
        ahora = datetime(2026, 11, 23, 3, 0, tzinfo=ZONA)
        self.assertIsNone(a.convertir('x', dict(EST, filas=[fila('2026-11-22T20:20:00')]), ZONA, ahora))
        self.assertIsNone(a.convertir('x', dict(EST, filas=[]), ZONA, ahora))
        self.assertIsNone(a.convertir('x', dict(EST, filas=[fila('2026-11-22T20:20:00', ta='')]), ZONA,
                                      datetime(2026, 11, 22, 21, 30, tzinfo=ZONA)))

    def test_lluvia_desde_medianoche_local(self):
        ahora = datetime(2026, 11, 22, 10, 0, tzinfo=ZONA)           # 09:00 UTC
        filas = [fila('2026-11-22T08:00:00', prec='1.5'),
                 fila('2026-11-21T23:10:00', prec='0.2'),            # 00:10 local: hoy
                 fila('2026-11-21T22:50:00', prec='4.0'),            # 23:50 local: ayer
                 fila('2026-11-22T08:10:00', prec=None)]
        self.assertEqual(a.lluvia_hoy(filas, ahora), 1.7)
        self.assertIsNone(a.lluvia_hoy([], ahora))

    def test_agrupar_filtra_zona_y_ordena(self):
        regs = [dict(idema='A', lat=37.9, lon=-1.2, ubi='X', alt=1, fint='2026-11-22T10:00:00', ta=1),
                dict(idema='A', lat=37.9, lon=-1.2, ubi='X', alt=1, fint='2026-11-22T11:00:00', ta=2),
                dict(idema='B', lat=40.4, lon=-3.7, ubi='MADRID', alt=1, fint='2026-11-22T11:00:00', ta=3)]
        g = agrupar(regs)
        self.assertEqual(list(g), ['A'])
        self.assertEqual(g['A']['filas'][0]['ta'], 2)

    def test_fundir_conserva_filas_antiguas(self):
        from aemet_descargar import fundir
        nuevo = {'A': {'filas': [{'fint': '2026-11-22T20:00:00+0000', 'ta': 1}]}}
        ant = {'A': {'filas': [{'fint': '2026-11-22T08:00:00+0000', 'ta': 2},
                               {'fint': '2026-11-20T08:00:00+0000', 'ta': 3}]}}
        f = fundir(nuevo, ant)['A']['filas']
        self.assertEqual([x['ta'] for x in f], [1, 2])


if __name__ == '__main__':
    unittest.main()
