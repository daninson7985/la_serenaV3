from django.apps import AppConfig


class ConsultaConfig(AppConfig):
    name = 'consulta'
    verbose_name = 'API de consulta SGR'

    def ready(self):
        # Registra el esquema de autenticación por token en la documentación Swagger.
        from consulta import esquema  # noqa: F401
