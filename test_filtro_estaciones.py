"""Pruebas del filtro de estaciones: python3 -m unittest test_filtro_estaciones"""
import os, tempfile, unittest
from datetime import datetime, timedelta, timezone
from filtro_estaciones import leer_desactivadas, filtrar_lecturas, anotar_descartes

AHORA = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)

def est(sid, lat=37.76, lon=-1.50, temp=20.0, hum=60, precip=0.0, dewpt=12.0, hace_min=2, **m):
    met = {'temp': temp, 'dewpt': dewpt, 'heatIndex': temp, 'windChill': temp,
           'pressure': 1015.0, 'windSpeed': 5.0, 'windGust': 9.0, 'precipTotal': precip}
    met.update(m)
    return {'stationID': sid, 'lat': lat, 'lon': lon, 'humidity': hum,
            'epoch': int((AHORA - timedelta(minutes=hace_min)).timestamp()),
            'solarRadiation': 400, 'uv': 3, 'metric': met}

def vecinas(n=5, temp=20.0):
    # A pocos km unas de otras, alrededor de Totana
    return [est(f'IV{i}', lat=37.76 + i * 0.01, lon=-1.50 + i * 0.01, temp=temp) for i in range(n)]

def snap(minutos_antes, estaciones):
    return {'timestamp': (AHORA - timedelta(minutes=minutos_antes)).isoformat(), 'stations': estaciones}

class Desactivadas(unittest.TestCase):
    def test_lee_ids_y_motivos(self):
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt', encoding='utf-8') as f:
            f.write("# comentario\n\nILORCA45   # mala\n  itotan8\n#IALHAM4\n")
        try:
            self.assertEqual(leer_desactivadas(f.name), {'ILORCA45', 'ITOTAN8'})
        finally:
            os.unlink(f.name)

    def test_sin_archivo(self):
        self.assertEqual(leer_desactivadas('/no/existe.txt'), set())

class Filtro(unittest.TestCase):
    def test_lecturas_normales_no_se_tocan(self):
        datos = vecinas()
        quedan, desc = filtrar_lecturas(datos, [], AHORA)
        self.assertEqual(len(quedan), 5)
        self.assertEqual(desc, [])
        self.assertNotIn('descartado', quedan[0])

    def test_fuera_de_rango_anula_el_campo_y_sus_derivados(self):
        e = est('IMALA', temp=71.0)
        quedan, desc = filtrar_lecturas([e], [], AHORA)
        self.assertEqual(len(quedan), 1)              # la estación sigue (el viento vale)
        self.assertIsNone(e['metric']['temp'])
        self.assertIsNone(e['metric']['heatIndex'])
        self.assertIsNone(e['metric']['dewpt'])
        self.assertEqual(e['metric']['windSpeed'], 5.0)
        self.assertIn('temp', e['descartado'])
        self.assertEqual([d[1] for d in desc], ['temp'])

    def test_humedad_cero(self):
        e = est('IMALA', hum=0)
        filtrar_lecturas([e], [], AHORA)
        self.assertIsNone(e['humidity'])
        self.assertIsNone(e['metric']['dewpt'])

    def test_humedad_del_uno_por_ciento(self):
        # IHELLN10 (oct 2026): 1 % de noche en otoño, sensor roto
        e = est('IMALA', hum=1.0)
        filtrar_lecturas([e], [], AHORA)
        self.assertIsNone(e['humidity'])
        self.assertIsNone(e['metric']['dewpt'])

    def test_lectura_vieja_se_quita_entera(self):
        quedan, desc = filtrar_lecturas([est('IVIEJA', hace_min=5 * 60)], [], AHORA)
        self.assertEqual(quedan, [])
        self.assertEqual(desc[0][1], 'observacion')

    def test_rocio_por_encima_de_temperatura(self):
        e = est('IMALA', temp=15.0, dewpt=22.0)
        filtrar_lecturas([e], [], AHORA)
        self.assertIsNone(e['metric']['dewpt'])
        self.assertEqual(e['metric']['temp'], 15.0)

    def test_salto_de_temperatura(self):
        prev = [snap(10, [est('IX', temp=18.0)])]
        e = est('IX', temp=31.0)
        filtrar_lecturas([e], prev, AHORA)
        self.assertIsNone(e['metric']['temp'])

    def test_bajada_normal_de_tormenta_no_salta(self):
        prev = [snap(10, [est('IX', temp=28.0)])]
        e = est('IX', temp=19.5)
        filtrar_lecturas([e], prev, AHORA)
        self.assertEqual(e['metric']['temp'], 19.5)

    def test_salto_antiguo_no_cuenta(self):
        prev = [snap(90, [est('IX', temp=10.0)])]
        e = est('IX', temp=25.0)
        filtrar_lecturas([e], prev, AHORA)
        self.assertEqual(e['metric']['temp'], 25.0)

    def test_compara_con_la_ultima_valida(self):
        # La de hace 5 min ya venía anulada: se compara con la de hace 20.
        malo = est('IX', temp=None)
        prev = [snap(20, [est('IX', temp=18.0)]), snap(5, [malo])]
        e = est('IX', temp=40.0)
        filtrar_lecturas([e], prev, AHORA)
        self.assertIsNone(e['metric']['temp'])

    def test_lluvia_de_golpe(self):
        prev = [snap(10, [est('IX', precip=1.2)])]
        e = est('IX', precip=180.0)
        filtrar_lecturas([e], prev, AHORA)
        self.assertIsNone(e['metric']['precipTotal'])

    def test_reinicio_de_medianoche_no_es_error(self):
        prev = [snap(10, [est('IX', precip=12.4)])]
        e = est('IX', precip=0.0)
        filtrar_lecturas([e], prev, AHORA)
        self.assertEqual(e['metric']['precipTotal'], 0.0)

    def test_temperatura_muy_distinta_de_las_vecinas(self):
        datos = vecinas(5, temp=20.0) + [est('ISOL', lat=37.77, lon=-1.49, temp=33.0)]
        quedan, desc = filtrar_lecturas(datos, [], AHORA)
        sol = [e for e in quedan if e['stationID'] == 'ISOL'][0]
        self.assertIsNone(sol['metric']['temp'])
        self.assertEqual([d[0] for d in desc], ['ISOL'])   # las vecinas no caen

    def test_pocas_vecinas_no_se_compara(self):
        datos = vecinas(2, temp=20.0) + [est('ISOL', lat=37.77, lon=-1.49, temp=33.0)]
        filtrar_lecturas(datos, [], AHORA)
        self.assertEqual(datos[-1]['metric']['temp'], 33.0)

    def test_vecinas_lejanas_no_cuentan(self):
        lejos = [est(f'IL{i}', lat=38.5 + i * 0.01, lon=-0.5, temp=20.0) for i in range(5)]
        datos = lejos + [est('ISOL', temp=33.0)]
        filtrar_lecturas(datos, [], AHORA)
        self.assertEqual(datos[-1]['metric']['temp'], 33.0)

class Registro(unittest.TestCase):
    def test_acumula_y_olvida(self):
        reg = {'IVIEJA': {'temp': {'veces': 3, 'primera': '2026-10-01T00:00+00:00',
                                   'ultima': '2026-10-02T00:00+00:00', 'valor': 70, 'motivo': 'x'}}}
        anotar_descartes(reg, [('IX', 'temp', 71.0, 'fuera de rango')], AHORA)
        anotar_descartes(reg, [('IX', 'temp', 72.0, 'fuera de rango')], AHORA)
        self.assertNotIn('IVIEJA', reg)
        self.assertEqual(reg['IX']['temp']['veces'], 2)
        self.assertEqual(reg['IX']['temp']['valor'], 72.0)

if __name__ == '__main__':
    unittest.main()
