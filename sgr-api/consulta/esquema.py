"""Describe la autenticación por token en el esquema OpenAPI (botón Authorize de Swagger)."""
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class TokenSGRScheme(OpenApiAuthenticationExtension):
    target_class = 'consulta.autenticacion.TokenSGRAuthentication'
    name = 'TokenSGR'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'description': 'Token obtenido en POST /api/v1/token/. Vence según API_TOKEN_HORAS.',
        }
