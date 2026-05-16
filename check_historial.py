import json, os, sys

f = 'historial_agricola.json'
if not os.path.exists(f):
    print('Sin historial — ejecutando fix')
    sys.exit(1)

h = json.load(open(f))
n = sum(1 for d in h.values() for v in d.values() if v.get('tempMax') is not None)
dias = len(h)
print(f'Historial: {dias} dias, {n} entradas con temperatura')

if n < 50:
    print('Historial insuficiente — ejecutando fix_historial.py')
    sys.exit(1)

print('Historial OK')
sys.exit(0)
