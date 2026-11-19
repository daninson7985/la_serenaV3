"""El menú solo muestra "Casos Sociales" a quienes pueden abrir la página (evita el 403 del Usuario de consulta)."""
from django.test import Client, TestCase
from django.urls import reverse

from sgr_app.models import Delegacion, Usuario

PASSWORD = 'TestPassword123!'


class MenuCasosSocialesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        delegacion = Delegacion.objects.create(nombre='Centro', codigo='CEN')
        crear = Usuario.objects.create_user
        cls.usuarios = {
            'admin': Usuario.objects.create_superuser(username='c.admin', password=PASSWORD, rol=Usuario.Rol.ADMINISTRADOR),
            'coordinador': crear(username='c.coord', password=PASSWORD, rol=Usuario.Rol.COORDINADOR),
            'delegado': crear(username='c.del', password=PASSWORD, rol=Usuario.Rol.DELEGADO, delegacion=delegacion),
            'consulta': crear(username='c.cons', password=PASSWORD, rol=Usuario.Rol.CONSULTA),
        }

    def _cliente(self, perfil):
        client = Client()
        client.force_login(self.usuarios[perfil])
        return client

    def test_enlace_coincide_con_el_acceso(self):
        url = reverse('web_casos_sociales')
        for perfil, puede in (('admin', True), ('coordinador', True), ('delegado', True), ('consulta', False)):
            with self.subTest(perfil=perfil):
                client = self._cliente(perfil)
                menu = client.get(reverse('web_semaforo')).content.decode()
                self.assertEqual(f'href="{url}"' in menu, puede)
                self.assertEqual(client.get(url).status_code, 200 if puede else 403)
