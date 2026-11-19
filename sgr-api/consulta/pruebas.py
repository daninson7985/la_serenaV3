"""Ejecutor de pruebas: crea en la base temporal ``sgr`` las tablas del SGR que la API lee.

En producción esas tablas existen (las crea el SGR); en pruebas la base parte vacía.
"""
from django.apps import apps
from django.db import connections
from django.test.runner import DiscoverRunner


class RunnerPruebas(DiscoverRunner):
    def setup_databases(self, **kwargs):
        config = super().setup_databases(**kwargs)
        from consulta.models import ModeloSGR
        modelos = [mod for mod in apps.get_app_config('consulta').get_models() if issubclass(mod, ModeloSGR)]
        with connections['sgr'].schema_editor() as editor:
            for modelo in modelos:
                editor.create_model(modelo)
        return config
