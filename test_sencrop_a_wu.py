import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from sencrop_a_wu import convertir, leer_sencrop

EST = {
    'id': 'chqp-j6f3-3lne', 'name': 'Costera / Ñorica',
    'latestMeasurementDate': '2026-11-22T14:55:00Z',
    'location': {'lat': 37.77, 'lng': -1.5},
    'state': {'isActive': True},
    'measurements': {
        'temperature': {'latestCelsius': 24.0},
        'dewPoint': {'latestCelsius': 4.1},
        'rainfall': {'todayMm': 0.4},
        'relativeHumidity': {'latestPercent': 27.3},
        'windSpeed': {'latestSpeedKph': 5.5},
        'windGust': {'lastHourMaxSpeedKph': 12.0},
        'windDirection': {'latestDirectionDegree': 200},
    },
}


class PruebasSencrop(unittest.TestCase):
    def test_convierte_a_formato_wu(self):
        o = convertir(EST, timezone.utc)
        self.assertEqual(o['stationID'], 'SC-chqp-j6f3-3lne')
        self.assertEqual(o['neighborhood'], 'Costera / Ñorica')
        self.assertEqual(o['humidity'], 27.3)
        self.assertEqual(o['metric']['temp'], 24.0)
        self.assertEqual(o['metric']['precipTotal'], 0.4)
        self.assertEqual(o['metric']['windSpeed'], 5.5)
        self.assertEqual(o['obsTimeLocal'], '2026-11-22 14:55:00')
        self.assertEqual(o['epoch'], int(datetime(2026, 11, 22, 14, 55, tzinfo=timezone.utc).timestamp()))

    def test_sin_ubicacion_o_inactiva_se_descarta(self):
        self.assertIsNone(convertir({**EST, 'location': {}}))
        self.assertIsNone(convertir({**EST, 'state': {'isActive': False}}))

    def test_campos_que_faltan_son_none(self):
        o = convertir({'id': 'x', 'location': {'lat': 37, 'lng': -1}})
        self.assertIsNone(o['metric']['temp'])
        self.assertIsNone(o['epoch'])

    def test_fichero_ausente_o_roto_no_rompe(self):
        self.assertEqual(leer_sencrop('/no/existe.json'), [])
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            f.write('{roto')
        self.assertEqual(leer_sencrop(f.name), [])
        os.unlink(f.name)

    def test_desactivadas(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump({'estaciones': [EST]}, f)
        self.assertEqual(len(leer_sencrop(f.name)), 1)
        self.assertEqual(leer_sencrop(f.name, desactivadas={'sc-chqp-j6f3-3lne'}), [])
        os.unlink(f.name)


if __name__ == '__main__':
    unittest.main()
