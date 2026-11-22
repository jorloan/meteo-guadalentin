import unittest
from datetime import datetime, timezone, timedelta

import sencrop_historial as sh

ZONA = timezone(timedelta(hours=1))
T0 = int(datetime(2026, 11, 20, 0, 0, tzinfo=ZONA).timestamp())   # medianoche local


def resp(**series):
    """Respuesta de la API con series {medida: {metrica: {epoch: valor}}}."""
    out = {}
    for medida, metricas in series.items():
        out[medida] = [{'metric': m, 'timeseries': [
            {'timestamp': datetime.fromtimestamp(e, timezone.utc).isoformat().replace('+00:00', 'Z'), 'value': v}
            for e, v in pts.items()]} for m, pts in metricas.items()]
    return {'response': {'stationMeasurements': out}}


PLANTILLA = {'stationID': 'SC-x', 'lat': 37.8, 'lon': -1.5, 'neighborhood': 'Mortí', 'humidity': 50,
             'winddir': 0, 'uv': None, 'solarRadiation': None, 'obsTimeLocal': '', 'epoch': 0,
             'metric': {'temp': 1, 'heatIndex': None, 'windChill': None, 'dewpt': 1, 'pressure': None,
                        'windSpeed': 1, 'windGust': 1, 'precipTotal': 0}}


class Pruebas(unittest.TestCase):
    def test_serie_horaria_ignora_valores_no_numericos_y_series_ajenas(self):
        r = resp(temperature={'temperature:interpolated': {T0: 10.0, T0 + 3600: None},
                              'temperature:max': {T0: 99}})
        s = sh.serie_horaria(r)
        self.assertEqual(s, {'temp': {T0: 10.0}})

    def test_serie_horaria_con_respuesta_rara(self):
        self.assertEqual(sh.serie_horaria({}), {})
        self.assertEqual(sh.serie_horaria(None), {})

    def test_interpola_entre_horas(self):
        s = {'temp': {T0: 10.0, T0 + 3600: 12.0}}
        o = sh.observacion(PLANTILLA, s, T0 + 1800, ZONA)
        self.assertEqual(o['metric']['temp'], 11.0)
        self.assertEqual(o['epoch'], T0 + 1800)
        self.assertEqual(o['obsTimeLocal'], '2026-11-20 00:30:00')

    def test_sin_temperatura_no_hay_observacion(self):
        self.assertIsNone(sh.observacion(PLANTILLA, {'hr': {T0: 50}}, T0, ZONA))

    def test_no_inventa_fuera_de_rango_ni_en_huecos(self):
        s = {'temp': {T0: 10.0, T0 + 6 * 3600: 20.0}}
        self.assertIsNone(sh.observacion(PLANTILLA, s, T0 + 3 * 3600, ZONA))
        self.assertIsNone(sh.observacion(PLANTILLA, s, T0 + 20 * 3600, ZONA))

    def test_lluvia_acumulada_se_reinicia_a_medianoche(self):
        horas = {T0 - 3600: 5.0, T0: 1.0, T0 + 3600: 2.0, T0 + 7200: 4.0}
        # a las 02:00 locales: 1 + 2 (la lluvia de 23:00 del día anterior no cuenta)
        self.assertEqual(sh._lluvia_acumulada(horas, T0 + 7200, ZONA), 3.0)
        # a las 02:30: suma media hora de la cubeta 02:00
        self.assertEqual(sh._lluvia_acumulada(horas, T0 + 9000, ZONA), 5.0)
        # a las 00:00 justas: nada acumulado aún del día (pero hay datos de lluvia: 0 no, None)
        self.assertIsNone(sh._lluvia_acumulada(horas, T0, ZONA))

    def test_direccion_no_se_interpola(self):
        s = {'temp': {T0: 10.0, T0 + 3600: 10.0}, 'dir': {T0: 350, T0 + 3600: 10}}
        o = sh.observacion(PLANTILLA, s, T0 + 1000, ZONA)
        self.assertEqual(o['winddir'], 350)

    def test_inyectar_solo_donde_falta_y_es_idempotente(self):
        s = {'SC-x': {'temp': {T0 + i * 3600: 10.0 + i for i in range(6)}}}
        fotos = [
            {'timestamp': datetime.fromtimestamp(T0 + 1800, ZONA).isoformat(), 'stations': [{'stationID': 'IA1'}]},
            {'timestamp': datetime.fromtimestamp(T0 + 5400, ZONA).isoformat(),
             'stations': [{'stationID': 'SC-x', 'metric': {'temp': 99.0}}]},   # ya tiene dato real
            {'timestamp': datetime.fromtimestamp(T0 + 50 * 3600, ZONA).isoformat(), 'stations': []},  # sin serie
        ]
        n = sh.inyectar(fotos, {'SC-x': PLANTILLA}, s, ZONA)
        self.assertEqual(n, 1)
        self.assertEqual(fotos[0]['stations'][1]['metric']['temp'], 10.5)
        self.assertEqual(fotos[1]['stations'][0]['metric']['temp'], 99.0)
        self.assertEqual(fotos[2]['stations'], [])
        self.assertEqual(sh.inyectar(fotos, {'SC-x': PLANTILLA}, s, ZONA), 0)

    def test_proyectar_precip(self):
        h = [{'timestamp': 't', 'stations': [{'stationID': 'a', 'metric': {'precipTotal': 1.0}},
                                              {'stationID': 'b', 'metric': {'precipTotal': None}}]}]
        self.assertEqual(sh.proyectar_precip(h),
                         [{'timestamp': 't', 'stations': [{'stationID': 'a', 'metric': {'precipTotal': 1.0}}]}])


if __name__ == '__main__':
    unittest.main()
