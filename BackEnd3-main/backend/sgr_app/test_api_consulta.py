"""API de consulta (solo lectura): catálogos y datos importados de los Excel."""
from django.test import Client, TestCase

from sgr_app.models import (
    Area, CartaSeguimiento, Delegacion, OrganizacionComunitaria, RegistroTuboTrabajo,
    Solicitante, SubatencionSocial, TipoAtencionSocial, Usuario,
)

PASSWORD = 'TestPassword123!'
ENDPOINTS = [
    'areas', 'solicitantes', 'tipos-atencion-social', 'subatenciones-sociales',
    'organizaciones', 'tubo-excel', 'cartas',
]


class ApiConsultaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cia = Delegacion.objects.create(nombre='Las Compañías', codigo='CIA')
        cls.cen = Delegacion.objects.create(nombre='Centro', codigo='CEN')
        area = Area.objects.create(nombre='GESTOR SOCIAL')
        tipo = TipoAtencionSocial.objects.create(area=area, nombre='GESTION DE SUBSIDIOS')
        SubatencionSocial.objects.create(tipo_atencion=tipo, nombre='PGU')
        Solicitante.objects.create(nombre='JJVV Villa Ejemplo', tipo_solicitante='INSTITUCION', direccion='Calle 1')
        OrganizacionComunitaria.objects.create(nombre='JJVV Compañías', territorio='CIAS', delegacion=cls.cia, fila_origen=2)
        OrganizacionComunitaria.objects.create(nombre='JJVV Centro', territorio='CENTRO', delegacion=cls.cen, fila_origen=3)
        RegistroTuboTrabajo.objects.create(hoja='TUBO COMPAÑIAS', fila_origen=3, actividad='Poda', delegacion=cls.cia, estatus='REALIZADO')
        RegistroTuboTrabajo.objects.create(hoja='TUBO', fila_origen=3, actividad='Retiro de basura', estatus='EN PROCESO')
        CartaSeguimiento.objects.create(hoja='CARTAS', fila_origen=3, remite='JJVV Ejemplo', estado='APROBADA')
        crear = Usuario.objects.create_user
        cls.usuarios = {
            'admin': Usuario.objects.create_superuser(username='api.admin', password=PASSWORD, rol=Usuario.Rol.ADMINISTRADOR),
            'coordinador': crear(username='api.coord', password=PASSWORD, rol=Usuario.Rol.COORDINADOR),
            'delegado_cen': crear(username='api.del', password=PASSWORD, rol=Usuario.Rol.DELEGADO, delegacion=cls.cen),
            'funcionario_cia': crear(username='api.func', password=PASSWORD, rol=Usuario.Rol.FUNCIONARIO, delegacion=cls.cia),
            'consulta': crear(username='api.cons', password=PASSWORD, rol=Usuario.Rol.CONSULTA),
        }

    def _get(self, perfil, ruta, **params):
        client = Client()
        client.force_login(self.usuarios[perfil])
        return client.get(f'/api/v1/{ruta}/', params)

    @staticmethod
    def _filas(respuesta):
        datos = respuesta.json()
        return datos['results'] if isinstance(datos, dict) else datos

    def test_requieren_sesion(self):
        for ruta in ENDPOINTS:
            with self.subTest(ruta=ruta):
                self.assertEqual(Client().get(f'/api/v1/{ruta}/').status_code, 403)

    def test_administrador_consulta_todos(self):
        for ruta in ENDPOINTS:
            with self.subTest(ruta=ruta):
                respuesta = self._get('admin', ruta)
                self.assertEqual(respuesta.status_code, 200)
                self.assertTrue(self._filas(respuesta))

    def test_son_de_solo_lectura(self):
        client = Client()
        client.force_login(self.usuarios['admin'])
        for ruta in ENDPOINTS:
            with self.subTest(ruta=ruta):
                self.assertEqual(client.post(f'/api/v1/{ruta}/', {}).status_code, 405)

    def test_listados_grandes_paginados(self):
        datos = self._get('admin', 'organizaciones', page_size=1).json()
        self.assertEqual(datos['count'], 2)
        self.assertEqual(len(datos['results']), 1)
        self.assertIsNotNone(datos['next'])

    def test_alcance_por_delegacion(self):
        self.assertEqual([o['nombre'] for o in self._filas(self._get('funcionario_cia', 'organizaciones'))], ['JJVV Compañías'])
        self.assertEqual([o['nombre'] for o in self._filas(self._get('delegado_cen', 'organizaciones'))], ['JJVV Centro'])
        self.assertEqual([r['actividad'] for r in self._filas(self._get('funcionario_cia', 'tubo-excel'))], ['Poda'])
        self.assertEqual(self._filas(self._get('delegado_cen', 'tubo-excel')), [])
        self.assertEqual(self._get('coordinador', 'tubo-excel').json()['count'], 2)

    def test_cartas_solo_sin_limite_territorial(self):
        self.assertEqual(self._get('consulta', 'cartas').json()['count'], 1)
        for perfil in ('funcionario_cia', 'delegado_cen'):
            with self.subTest(perfil=perfil):
                self.assertEqual(self._get(perfil, 'cartas').json()['count'], 0)

    def test_solicitantes_no_para_consulta_ni_datos_de_contacto(self):
        self.assertEqual(self._get('consulta', 'solicitantes').status_code, 403)
        fila = self._filas(self._get('funcionario_cia', 'solicitantes'))[0]
        self.assertFalse(set(fila) & {'run', 'telefono', 'correo'})

    def test_filtros(self):
        self.assertEqual(self._get('admin', 'tubo-excel', estatus='REALIZADO').json()['count'], 1)
        self.assertEqual(self._get('admin', 'organizaciones', q='centro').json()['count'], 1)
        self.assertEqual(self._get('admin', 'cartas', estado='NO APLICA').json()['count'], 0)

    def test_ajustes_de_incentivo_por_rol(self):
        from sgr_app.models import AjusteIncentivo, ConceptoAjuste, PeriodoMedicion
        reclamo = ConceptoAjuste.objects.create(nombre='RECLAMOS', naturaleza='NEGATIVO')
        periodo = PeriodoMedicion.objects.create(nombre='T3 prueba')
        otro = Usuario.objects.create_user(username='api.otro', password=PASSWORD, rol=Usuario.Rol.FUNCIONARIO, delegacion=self.cia)
        for funcionario in (self.usuarios['funcionario_cia'], otro):
            AjusteIncentivo.objects.create(funcionario=funcionario, concepto=reclamo, periodo=periodo,
                                           motivo='Sin registro', valor_porcentaje=30)
        fila = self._filas(self._get('admin', 'ajustes-incentivo'))[0]
        self.assertEqual(fila['efecto_porcentaje'], -30.0)
        self.assertEqual(self._get('coordinador', 'ajustes-incentivo').json()['count'], 2)
        self.assertEqual(self._get('funcionario_cia', 'ajustes-incentivo').json()['count'], 1)
        for perfil in ('delegado_cen', 'consulta'):
            with self.subTest(perfil=perfil):
                self.assertEqual(self._get(perfil, 'ajustes-incentivo').status_code, 403)
        self.assertIn('RECLAMOS', [c['nombre'] for c in self._filas(self._get('consulta', 'conceptos-ajuste'))])

    def test_roles_solo_admin_y_coordinador(self):
        self.assertEqual(self._get('admin', 'roles').status_code, 200)
        self.assertEqual(self._get('coordinador', 'roles').status_code, 200)
        for perfil in ('delegado_cen', 'funcionario_cia', 'consulta'):
            with self.subTest(perfil=perfil):
                self.assertEqual(self._get(perfil, 'roles').status_code, 403)
        self.assertEqual(self._get('funcionario_cia', 'tipos-actividad').status_code, 200)

    def test_documentados_en_openapi(self):
        client = Client()
        client.force_login(self.usuarios['admin'])
        esquema = client.get('/api/v1/schema/', HTTP_ACCEPT='application/vnd.oai.openapi+json').json()
        for ruta in ENDPOINTS + ['roles', 'tipos-actividad', 'conceptos-ajuste', 'ajustes-incentivo']:
            with self.subTest(ruta=ruta):
                self.assertIn(f'/api/v1/{ruta}/', esquema['paths'])
