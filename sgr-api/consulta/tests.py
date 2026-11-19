"""Pruebas de la API de consulta. Usan bases temporales: nunca tocan la base real del SGR."""
import base64
import hashlib
import hmac
import time
from datetime import date, timedelta

from django.contrib.auth.hashers import make_password
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from consulta import models as m

CLAVE = 'ClaveDePrueba123!'
SECRETO_2FA = base64.b32encode(b'12345678901234567890').decode()


def crear(modelo, **campos):
    """Inserta filas en la base temporal del SGR (save() está bloqueado en los modelos del SGR)."""
    obj = modelo(**campos)
    modelo.objects.bulk_create([obj])
    return obj


def codigo_totp(secreto):
    clave = base64.b32decode(secreto)
    digest = hmac.new(clave, (int(time.time()) // 30).to_bytes(8, 'big'), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    return f'{(int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF) % 1_000_000:06d}'


class BaseAPI(TestCase):
    databases = {'default', 'sgr'}

    @classmethod
    def setUpTestData(cls):
        cls.cia = crear(m.DelegacionSGR, id=1, nombre='Las Compañías', codigo='CIA', activo=True, ambito='Urbano')
        cls.cen = crear(m.DelegacionSGR, id=2, nombre='Centro', codigo='CEN', activo=True, ambito='Urbano')
        hash_clave = make_password(CLAVE)
        base = dict(password=hash_clave, last_name='', is_superuser=False, is_active=True,
                    requires_2fa=False, must_change_password=False)
        cls.admin = crear(m.UsuarioSGR, id=1, username='admin', first_name='Admin', rol='ADMINISTRADOR', **base)
        cls.coord = crear(m.UsuarioSGR, id=2, username='coord', first_name='Coord', rol='COORDINADOR', **base)
        cls.delegado = crear(m.UsuarioSGR, id=3, username='delegado', first_name='Del', rol='DELEGADO', delegacion_id=2, **base)
        cls.func = crear(m.UsuarioSGR, id=4, username='func', first_name='Func', rol='FUNCIONARIO', delegacion_id=1, **base)
        cls.consulta = crear(m.UsuarioSGR, id=5, username='consulta', first_name='Cons', rol='CONSULTA', **base)
        crear(m.UsuarioSGR, id=6, username='inactivo', first_name='X', rol='FUNCIONARIO', **{**base, 'is_active': False})
        crear(m.UsuarioSGR, id=7, username='nuevo', first_name='X', rol='FUNCIONARIO', **{**base, 'must_change_password': True})
        crear(m.UsuarioSGR, id=8, username='con2fa', first_name='X', rol='COORDINADOR', totp_secret=SECRETO_2FA,
              **{**base, 'requires_2fa': True})

        crear(m.OrganizacionSGR, id=1, nombre='JJVV Compañías', domicilio_legal='Sin registro', territorio='CIAS',
              delegacion_id=1, numero_registro_pj='1', registro_dir='1', fila_origen=2, observacion_importacion='')
        crear(m.OrganizacionSGR, id=2, nombre='JJVV Centro', domicilio_legal='Calle 1', territorio='CENTRO',
              delegacion_id=2, numero_registro_pj='2', registro_dir='2', fila_origen=3, observacion_importacion='')
        tubo = dict(interno_externo='INT', solicitante='Vecino', territorio='Toqui', responsable='Sin registro',
                    area_apoyo='Sin registro', avance_observaciones='', codigo_verificacion_foto='', observacion_importacion='')
        crear(m.RegistroTuboSGR, id=1, hoja='TUBO COMPAÑIAS', fila_origen=3, actividad='Poda', delegacion_id=1, estatus='REALIZADO', **tubo)
        crear(m.RegistroTuboSGR, id=2, hoja='TUBO', fila_origen=3, actividad='Retiro de basura', estatus='EN PROCESO', **tubo)
        crear(m.CartaSGR, id=1, hoja='CARTAS', fila_origen=3, numero='1', para='Delegado', remite='JJVV Ejemplo',
              fono_contacto='', actividad_tema='Evento', encargado_seguimiento='X', estado='APROBADA',
              pronunciamiento='', derivada_a='', observacion='', observacion_importacion='')
        crear(m.SolicitanteSGR, id=1, nombre='JJVV Villa Ejemplo', apellido='', tipo_solicitante='INSTITUCION',
              direccion='Calle 2', estado=True)
        compromiso = dict(origen='INT', solicitante='Vecino', territorio='Toqui', fecha_registro=timezone.now(),
                          fecha_compromiso=date(2026, 8, 1), fecha_comprometida=date(2026, 8, 1),
                          area_apoyo='Social', descripcion='Visita', estado='PENDIENTE', anulado=False)
        crear(m.CompromisoSGR, id=1, delegacion_id=1, responsable_id=4, creado_por_id=4, **compromiso)
        crear(m.CompromisoSGR, id=2, delegacion_id=1, responsable_id=2, **compromiso)
        crear(m.CompromisoSGR, id=3, delegacion_id=2, responsable_id=3, **{**compromiso, 'anulado': True})
        crear(m.ConceptoAjusteSGR, id=1, nombre='RECLAMOS', naturaleza='NEGATIVO', activo=True)
        crear(m.PeriodoSGR, id=1, nombre='T3 2026', fecha_inicio=date(2026, 7, 1), fecha_termino=date(2026, 9, 30),
              dias_computables=92, cerrado=False, estado=True, umbral_semaforo_verde=100, umbral_semaforo_ambar=60,
              umbral_colectivo=80, tope_cumplimiento=150)
        ajuste = dict(tipo='RECLAMOS', concepto_id=1, motivo='Sin registro', valor_porcentaje=30,
                      fecha_registro=timezone.now(), periodo_id=1, estado='PENDIENTE')
        crear(m.AjusteIncentivoSGR, id=1, funcionario_id=4, **ajuste)
        crear(m.AjusteIncentivoSGR, id=2, funcionario_id=2, **ajuste)

    def token(self, username, **extra):
        r = APIClient().post('/api/v1/token/', {'username': username, 'password': CLAVE, **extra}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['token']

    def cliente(self, username):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token(username)}')
        return c

    def total(self, username, ruta, **params):
        r = self.cliente(username).get(f'/api/v1/{ruta}/', params)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['count']


class TokenTests(BaseAPI):
    def test_token_valido_permite_consultar(self):
        r = APIClient().post('/api/v1/token/', {'username': 'admin', 'password': CLAVE}, format='json')
        datos = r.json()
        self.assertEqual(datos['tipo'], 'Bearer')
        self.assertEqual(datos['usuario']['rol'], 'ADMINISTRADOR')
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {datos["token"]}')
        self.assertEqual(c.get('/api/v1/yo/').json()['username'], 'admin')
        # Solo se guarda la huella del token, nunca el token.
        self.assertFalse(m.TokenAcceso.objects.filter(huella=datos['token']).exists())

    def test_credenciales_incorrectas_o_cuenta_inactiva(self):
        for username, clave in (('admin', 'mala'), ('noexiste', CLAVE), ('inactivo', CLAVE)):
            with self.subTest(username=username):
                r = APIClient().post('/api/v1/token/', {'username': username, 'password': clave}, format='json')
                self.assertEqual(r.status_code, 401)
                self.assertNotIn('token', r.json())

    def test_cambio_de_contrasena_pendiente(self):
        r = APIClient().post('/api/v1/token/', {'username': 'nuevo', 'password': CLAVE}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_verificacion_en_dos_pasos(self):
        r = APIClient().post('/api/v1/token/', {'username': 'con2fa', 'password': CLAVE}, format='json')
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.json()['requires_2fa'])
        r = APIClient().post('/api/v1/token/', {'username': 'con2fa', 'password': CLAVE, 'codigo_2fa': '000000'}, format='json')
        self.assertEqual(r.status_code, 401)
        self.token('con2fa', codigo_2fa=codigo_totp(SECRETO_2FA))

    def test_bloqueo_tras_intentos_fallidos(self):
        for _ in range(5):
            APIClient().post('/api/v1/token/', {'username': 'func', 'password': 'mala'}, format='json')
        r = APIClient().post('/api/v1/token/', {'username': 'func', 'password': CLAVE}, format='json')
        self.assertEqual(r.status_code, 429)

    def test_sin_token_revocado_o_vencido_no_entra(self):
        self.assertEqual(APIClient().get('/api/v1/organizaciones/').status_code, 401)
        c = self.cliente('admin')
        self.assertEqual(c.post('/api/v1/token/revocar/').status_code, 204)
        self.assertEqual(c.get('/api/v1/organizaciones/').status_code, 401)
        token = self.token('admin')
        m.TokenAcceso.objects.update(expira_en=timezone.now() - timedelta(minutes=1))
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(c.get('/api/v1/organizaciones/').status_code, 401)


class AlcanceTests(BaseAPI):
    def test_datos_excel_por_delegacion(self):
        self.assertEqual(self.total('admin', 'organizaciones'), 2)
        self.assertEqual(self.total('func', 'organizaciones'), 1)
        self.assertEqual(self.total('delegado', 'organizaciones'), 1)
        self.assertEqual(self.total('func', 'tubo-excel'), 1)
        self.assertEqual(self.total('delegado', 'tubo-excel'), 0)
        self.assertEqual(self.total('consulta', 'tubo-excel'), 2)

    def test_cartas_solo_sin_limite_territorial(self):
        self.assertEqual(self.total('coord', 'cartas'), 1)
        self.assertEqual(self.total('consulta', 'cartas'), 1)
        self.assertEqual(self.total('func', 'cartas'), 0)
        self.assertEqual(self.total('delegado', 'cartas'), 0)

    def test_compromisos(self):
        self.assertEqual(self.total('admin', 'compromisos'), 2)  # el anulado no aparece
        self.assertEqual(self.total('func', 'compromisos'), 1)  # solo el suyo
        self.assertEqual(self.total('delegado', 'compromisos'), 0)  # su delegación solo tiene el anulado

    def test_usuarios_sin_datos_sensibles(self):
        self.assertEqual(self.total('func', 'usuarios'), 1)
        fila = self.cliente('admin').get('/api/v1/usuarios/').json()['results'][0]
        self.assertFalse(set(fila) & {'password', 'totp_secret', 'rut_anonimizado', 'telefono', 'email'})

    def test_solicitantes_y_roles(self):
        self.assertEqual(self.cliente('consulta').get('/api/v1/solicitantes/').status_code, 403)
        self.assertEqual(self.total('func', 'solicitantes'), 1)
        self.assertEqual(self.cliente('func').get('/api/v1/roles/').status_code, 403)
        self.assertEqual(self.cliente('coord').get('/api/v1/roles/').status_code, 200)

    def test_ajustes_de_incentivo(self):
        self.assertEqual(self.total('admin', 'ajustes-incentivo'), 2)
        self.assertEqual(self.total('func', 'ajustes-incentivo'), 1)
        self.assertEqual(self.cliente('delegado').get('/api/v1/ajustes-incentivo/').status_code, 403)
        fila = self.cliente('admin').get('/api/v1/ajustes-incentivo/1/').json()
        self.assertEqual(fila['efecto_porcentaje'], -30.0)

    def test_filtros_y_paginacion(self):
        self.assertEqual(self.total('admin', 'tubo-excel', estatus='REALIZADO'), 1)
        self.assertEqual(self.total('admin', 'organizaciones', q='centro'), 1)
        datos = self.cliente('admin').get('/api/v1/organizaciones/', {'page_size': 1}).json()
        self.assertEqual(len(datos['results']), 1)
        self.assertIsNotNone(datos['next'])


class SoloLecturaTests(BaseAPI):
    def test_no_acepta_escrituras(self):
        c = self.cliente('admin')
        for ruta in ('organizaciones', 'compromisos', 'usuarios', 'ajustes-incentivo'):
            with self.subTest(ruta=ruta):
                self.assertEqual(c.post(f'/api/v1/{ruta}/', {}, format='json').status_code, 405)
                self.assertEqual(c.delete(f'/api/v1/{ruta}/1/').status_code, 405)

    def test_modelos_del_sgr_no_se_guardan(self):
        org = m.OrganizacionSGR.objects.get(pk=1)
        with self.assertRaises(PermissionDenied):
            org.save()
        with self.assertRaises(PermissionDenied):
            org.delete()


class DocumentacionTests(BaseAPI):
    def test_swagger_y_esquema_openapi(self):
        self.assertEqual(APIClient().get('/api/v1/docs/').status_code, 200)
        esquema = APIClient().get('/api/v1/schema/', HTTP_ACCEPT='application/vnd.oai.openapi+json').json()
        self.assertTrue(esquema['openapi'].startswith('3.'))
        for ruta in ('/api/v1/token/', '/api/v1/organizaciones/', '/api/v1/tubo-excel/', '/api/v1/ajustes-incentivo/'):
            self.assertIn(ruta, esquema['paths'])
        self.assertEqual(esquema['components']['securitySchemes']['TokenSGR']['scheme'], 'bearer')
