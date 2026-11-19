"""Los botones visibles llevan a páginas que el usuario puede abrir (sin 403/404/500)."""
import re

from django.contrib.staticfiles import finders
from django.test import Client, TestCase
from django.urls import reverse

from sgr_app.models import Delegacion, Usuario

PASSWORD = 'TestPassword123!'


class BotonesPorRolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        delegacion = Delegacion.objects.create(nombre='Centro', codigo='CEN')
        cls.delegado = Usuario.objects.create_user(
            username='b.del', password=PASSWORD, rol=Usuario.Rol.DELEGADO, delegacion=delegacion,
        )
        cls.consulta = Usuario.objects.create_user(username='b.cons', password=PASSWORD, rol=Usuario.Rol.CONSULTA)

    def _cliente(self, usuario):
        client = Client()
        client.force_login(usuario)
        return client

    def test_panel_delegado_sin_periodo_none(self):
        # Sin período guardado para el trimestre actual, los enlaces no deben llevar "periodo=None".
        client = self._cliente(self.delegado)
        html = client.get(reverse('web_dashboard')).content.decode()
        self.assertNotIn('periodo=None', html)
        for href in set(re.findall(r'href="(/(?:tubo|informes)/\?[^"]*)"', html)):
            with self.subTest(href=href):
                self.assertEqual(client.get(href.replace('&amp;', '&')).status_code, 200)

    def test_brechas_historicas_solo_si_puede_abrirla(self):
        url = reverse('web_brechas_historicas')
        for usuario in (self.delegado, self.consulta):
            with self.subTest(usuario=usuario.username):
                client = self._cliente(usuario)
                self.assertNotIn(f'href="{url}"', client.get(reverse('web_dashboard')).content.decode())
                self.assertEqual(client.get(url).status_code, 403)

    def test_consulta_no_ve_botones_de_registro(self):
        client = self._cliente(self.consulta)
        tubo = client.get(reverse('web_tubo')).content.decode()
        self.assertNotIn(f'href="{reverse("web_crear_compromiso")}"', tubo)
        personal = client.get(reverse('web_personal')).content.decode()
        self.assertNotIn(f'href="{reverse("web_registrar_actividad_diaria")}"', personal)

    def test_imagen_de_evidencia_sin_foto_existe(self):
        self.assertIsNotNone(finders.find('img/evidencia_terreno_placeholder.svg'))
