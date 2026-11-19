"""Importa las planillas Excel de organizaciones (JJVV) y de la matriz SGR.

Uso (desde backend/):
    python manage.py importar_excel_jjvv
    python manage.py importar_excel_jjvv --jjvv RUTA.xlsx --matriz RUTA.xlsx

Cada registro se identifica por su hoja y fila de origen: si se vuelve a
importar, el registro existente se actualiza en vez de duplicarse. No se
elimina nada de la base de datos.
"""
import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sgr_app.models import CartaSeguimiento, Delegacion, OrganizacionComunitaria, RegistroTuboTrabajo

CARPETA_EXCEL = Path(settings.BASE_DIR).parent / 'jjvv.xlsx'
ARCHIVO_JJVV = 'base datos JJVV sin verificar.xlsx'
ARCHIVO_MATRIZ = 'Copia INACAP 3ER COMPAÑIAS MATRIZ SGR TRIMESTRE 2026 REV (1).xlsx'

# Delegaciones que aparecen en las planillas (mismos códigos que poblar_sgr).
DELEGACIONES_EXCEL = {
    'ADM': 'Avenida del Mar',
    'CEN': 'Centro',
    'ANT': 'La Antena - La Florida',
    'CIA': 'Las Compañías',
    'PAM': 'La Pampa',
    'RUR': 'Rural',
}

# Territorio de la planilla JJVV -> código de Delegacion.
TERRITORIO_A_DELEGACION = {
    'CIAS': 'CIA',
    'CENTRO': 'CEN',
    'PAMPA': 'PAM',
    'RURAL': 'RUR',
    'ANTENA': 'ANT',
    'AV DEL MAR': 'ADM',
}
HOJAS_TUBO = {
    # hoja: (código de delegación o None, ¿tiene columna N "código verificación foto"?)
    'TUBO COMPAÑIAS': ('CIA', False),
    'TUBO ANTENA': ('ANT', True),
    'TUBO': (None, True),
}
HOJAS_CARTAS = ['TUBO CARTAS', 'CARTAS ']


def texto(valor):
    if valor is None:
        return ''
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def fecha(valor, campo, notas):
    if valor is None or texto(valor) == '':
        return None
    if isinstance(valor, datetime.datetime):
        return valor.date()
    if isinstance(valor, datetime.date):
        return valor
    for formato in ('%d-%m-%Y', '%d/%m/%Y', '%d-%m-%y', '%d/%m/%y', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(texto(valor), formato).date()
        except ValueError:
            pass
    notas.append(f'{campo}: {texto(valor)}')
    return None


def entero(valor, campo, notas):
    if valor is None or texto(valor) == '':
        return None
    if isinstance(valor, (int, float)) and float(valor).is_integer() and valor >= 0:
        return int(valor)
    notas.append(f'{campo}: {texto(valor)}')
    return None


def vacia(valor):
    return texto(valor) == ''


class Command(BaseCommand):
    help = 'Importa las planillas Excel de organizaciones comunitarias (JJVV) y de la matriz SGR (tubos y cartas).'

    def add_arguments(self, parser):
        parser.add_argument('--jjvv', default=str(CARPETA_EXCEL / ARCHIVO_JJVV), help='Planilla de organizaciones JJVV.')
        parser.add_argument('--matriz', default=str(CARPETA_EXCEL / ARCHIVO_MATRIZ), help='Planilla de la matriz SGR.')

    def handle(self, *args, **options):
        try:
            import openpyxl
        except ImportError as exc:
            raise CommandError('Falta openpyxl: ejecuta "pip install -r requirements.txt".') from exc

        for clave in ('jjvv', 'matriz'):
            if not Path(options[clave]).is_file():
                raise CommandError(f'No se encontró el archivo: {options[clave]}')

        with transaction.atomic():
            # Delegaciones que mencionan las planillas: solo nombre y código.
            self.delegaciones = {}
            for codigo, nombre in DELEGACIONES_EXCEL.items():
                delegacion, creada = Delegacion.objects.get_or_create(codigo=codigo, defaults={'nombre': nombre})
                self.delegaciones[codigo] = delegacion
                if creada:
                    self.stdout.write(f'  Delegación creada: {delegacion}')

            libro = openpyxl.load_workbook(options['jjvv'], data_only=True, read_only=True)
            self.importar_jjvv(libro.worksheets[0])
            libro.close()

            libro = openpyxl.load_workbook(options['matriz'], data_only=True, read_only=True)
            for hoja, (codigo, con_foto) in HOJAS_TUBO.items():
                self.importar_tubo(libro[hoja], hoja, codigo, con_foto)
            for hoja in HOJAS_CARTAS:
                self.importar_cartas(libro[hoja], hoja)
            libro.close()

        self.stdout.write(self.style.SUCCESS('Importación terminada.'))

    def _informar(self, nombre, creados, actualizados):
        self.stdout.write(f'  {nombre}: {creados} nuevos, {actualizados} actualizados')

    def importar_jjvv(self, hoja):
        creados = actualizados = 0
        for fila, f in enumerate(hoja.iter_rows(min_row=2, max_col=8, values_only=True), start=2):
            if vacia(f[0]):
                continue
            notas = []
            territorio = texto(f[2])
            datos = {
                'nombre': texto(f[0]),
                'domicilio_legal': texto(f[1]),
                'territorio': territorio,
                'delegacion': self.delegaciones.get(TERRITORIO_A_DELEGACION.get(territorio.upper())),
                'socios_activos': entero(f[3], 'Socios activos', notas),
                'fecha_constitucion': fecha(f[4], 'Fecha constitución', notas),
                'numero_registro_pj': texto(f[5]),
                'fecha_inscripcion_registro': fecha(f[6], 'Fecha inscripción', notas),
                'registro_dir': texto(f[7]),
            }
            datos['observacion_importacion'] = '; '.join(notas)
            _, nuevo = OrganizacionComunitaria.objects.update_or_create(fila_origen=fila, defaults=datos)
            creados += nuevo
            actualizados += not nuevo
        self._informar('Organizaciones comunitarias', creados, actualizados)

    def importar_tubo(self, hoja, nombre, codigo, con_foto):
        creados = actualizados = 0
        for fila, f in enumerate(hoja.iter_rows(min_row=3, max_col=14, values_only=True), start=3):
            if vacia(f[2]):  # columna C: actividad / solicitud
                continue
            notas = []
            datos = {
                'numero': entero(f[0], 'N°', notas),
                'fecha_solicitud': fecha(f[1], 'Fecha solicitud', notas),
                'actividad': texto(f[2]),
                'interno_externo': texto(f[3]),
                'solicitante': texto(f[4]),
                'territorio': texto(f[5]),
                'delegacion': self.delegaciones.get(codigo),
                'responsable': texto(f[6]),
                'fecha_compromiso': fecha(f[7], 'Fecha compromiso', notas),
                'area_apoyo': texto(f[9]),
                'avance_observaciones': texto(f[10]),
                'estatus': texto(f[11]),
                'codigo_verificacion_foto': texto(f[13]) if con_foto else '',
            }
            datos['observacion_importacion'] = '; '.join(notas)
            _, nuevo = RegistroTuboTrabajo.objects.update_or_create(hoja=nombre, fila_origen=fila, defaults=datos)
            creados += nuevo
            actualizados += not nuevo
        self._informar(f'Tubo "{nombre}"', creados, actualizados)

    def importar_cartas(self, hoja, nombre):
        creados = actualizados = 0
        for fila, f in enumerate(hoja.iter_rows(min_row=3, max_col=14, values_only=True), start=3):
            if vacia(f[2]):  # columna C: fecha de la carta
                continue
            notas = []
            datos = {
                'fecha': fecha(f[2], 'Fecha', notas),
                'numero': texto(f[3]),
                'para': texto(f[4]),
                'remite': texto(f[5]),
                'fono_contacto': texto(f[6]),
                'actividad_tema': texto(f[7]),
                'fecha_actividad': fecha(f[8], 'Fecha actividad', notas),
                'encargado_seguimiento': texto(f[9]),
                'estado': texto(f[10]),
                'pronunciamiento': texto(f[11]),
                'derivada_a': texto(f[12]),
                'observacion': texto(f[13]),
            }
            datos['observacion_importacion'] = '; '.join(notas)
            _, nuevo = CartaSeguimiento.objects.update_or_create(hoja=nombre.strip(), fila_origen=fila, defaults=datos)
            creados += nuevo
            actualizados += not nuevo
        self._informar(f'Cartas "{nombre.strip()}"', creados, actualizados)
