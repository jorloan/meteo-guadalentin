import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import chs_a_wu as c

ZONA = timezone(timedelta(hours=1))


def t(h, m, dia=22):
    return datetime(2026, 11, dia, h, m, tzinfo=ZONA)


class Pruebas(unittest.TestCase):
    def test_num(self):
        self.assertEqual(c.num('12,3'), 12.3)
        self.assertEqual(c.num('0,0'), 0.0)
        for x in ('-', '', None, 'abc'):
            self.assertIsNone(c.num(x))

    def test_fecha_y_nombre(self):
        self.assertEqual(c.fecha('22-11-2026 17:05', ZONA), t(17, 5))
        self.assertIsNone(c.fecha('01-10-2000', ZONA))
        self.assertEqual(c.limpiar_nombre('EM.AgAbParetón'), 'AgAbParetón')
        self.assertEqual(c.limpiar_nombre('Pl. Caravaca'), 'Caravaca')
        self.assertEqual(c.limpiar_nombre('E.Santomera'), 'E.Santomera')

    def test_lluvia_suma_horas_cerradas(self):
        est = {}
        # 10:03 -> cierra la hora 9 con 2.0 mm ; 11:04 -> cierra la 10 con 1.0 mm
        c.acumular_lluvia(est, 'X', {'1h': 2.0}, t(10, 3))
        c.acumular_lluvia(est, 'X', {'1h': 1.0}, t(11, 4))
        # 11:30: parcial = 0.5 - 1.0*(30/60) = 0
        self.assertEqual(c.acumular_lluvia(est, 'X', {'1h': 0.5}, t(11, 30)), 3.0)
        # 11:50: la última hora ya trae lluvia nueva: 1.2 - 1.0*(10/60) = 1.03
        self.assertEqual(c.acumular_lluvia(est, 'X', {'1h': 1.2}, t(11, 50)), 4.0)

    def test_hora_cerrada_se_anota_una_sola_vez(self):
        est = {}
        c.acumular_lluvia(est, 'X', {'1h': 2.0}, t(10, 2))
        c.acumular_lluvia(est, 'X', {'1h': 2.5}, t(10, 7))   # otro ciclo en :00-:09: no sobrescribe
        self.assertEqual(est['X']['horas']['9'], 2.0)

    def test_cota_inferior_con_ventanas(self):
        est = {}
        # primer ciclo del día a las 17:30 sin historia: no puede ser menos que la ventana de 12 h
        r = c.acumular_lluvia(est, 'X', {'1h': 0.0, '12h': 4.2, '24h': 9.0}, t(17, 30))
        self.assertEqual(r, 4.2)      # la de 24 h no cabe en hoy (17,5 h)

    def test_reinicio_a_medianoche(self):
        est = {}
        c.acumular_lluvia(est, 'X', {'1h': 3.0}, t(10, 2))
        r = c.acumular_lluvia(est, 'X', {'1h': 0.0}, t(0, 30, dia=23))
        self.assertEqual(r, 0.0)
        self.assertEqual(est['X']['dia'], '2026-11-23')

    def test_sin_dato_de_1h(self):
        self.assertIsNone(c.acumular_lluvia({}, 'X', {'1h': None}, t(10, 0)))

    def test_convertir_ignora_dato_viejo_y_usa_el_fresco(self):
        punto = {'nombre': 'EM.Cenajo', 'temp': 17.2, 'humedad': None,
                 'fecha_temp': '22-11-2026 17:00', 'lluvia_hoy': 0.4, 'fecha_lluvia': '22-11-2026 17:05'}
        o = c.convertir('04S03', punto, 38.36, -1.77, ZONA, t(17, 10))
        self.assertEqual(o['stationID'], 'CH-04S03')
        self.assertEqual(o['neighborhood'], 'CHS · Cenajo')
        self.assertEqual(o['metric']['temp'], 17.2)
        self.assertEqual(o['metric']['precipTotal'], 0.4)
        self.assertEqual(o['obsTimeLocal'], '2026-11-22 17:05:00')
        # temperatura de hace 9 h: sensor caído -> solo queda la lluvia
        punto['fecha_temp'] = '22-11-2026 08:00'
        o = c.convertir('04S03', punto, 38.36, -1.77, ZONA, t(17, 10))
        self.assertIsNone(o['metric']['temp'])
        self.assertEqual(o['metric']['precipTotal'], 0.4)
        # todo viejo -> nada
        punto['fecha_lluvia'] = '16-06-2026 13:10'
        self.assertIsNone(c.convertir('04S03', punto, 38.36, -1.77, ZONA, t(17, 10)))

    def test_convertir_sin_coordenadas(self):
        self.assertIsNone(c.convertir('X', {'temp': 1, 'fecha_temp': '22-11-2026 17:00'}, None, None, ZONA, t(17, 5)))

    def test_leer_chs_tolerante(self):
        self.assertEqual(c.leer_chs('/no/existe.json', '/no/existe2.json', (), ZONA, t(17, 0)), [])
        with tempfile.TemporaryDirectory() as d:
            f1, f2 = os.path.join(d, 'chs.json'), os.path.join(d, 'coords.json')
            json.dump({'puntos': {'04S03': {'nombre': 'EM.Cenajo', 'temp': 17.2, 'fecha_temp': '22-11-2026 17:00'},
                                  '99Z99': {'nombre': 'sin coordenadas', 'temp': 1, 'fecha_temp': '22-11-2026 17:00'}}},
                      open(f1, 'w'))
            json.dump({'puntos': {'04S03': [38.36, -1.77]}}, open(f2, 'w'))
            r = c.leer_chs(f1, f2, (), ZONA, t(17, 10))
            self.assertEqual([o['stationID'] for o in r], ['CH-04S03'])
            self.assertEqual(c.leer_chs(f1, f2, ('ch-04s03',), ZONA, t(17, 10)), [])


if __name__ == '__main__':
    unittest.main()
