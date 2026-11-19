"""Autenticación por token (``Authorization: Bearer <token>``) y validación de credenciales del SGR."""
import base64
import binascii
import hashlib
import hmac
import re
import time
from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from consulta.models import TokenAcceso, UsuarioSGR


def huella(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def codigo_totp_valido(secreto, codigo):
    """TOTP RFC 6238 (30 s, 6 dígitos, ±1 intervalo). Igual que sgr_app.web_views.codigo_totp_valido."""
    if not secreto or not re.fullmatch(r'\d{6}', codigo or ''):
        return False
    try:
        clave = base64.b32decode(secreto.upper() + '=' * (-len(secreto) % 8), casefold=True)
    except (binascii.Error, ValueError):
        return False
    contador = int(time.time()) // 30
    for candidato in range(contador - 1, contador + 2):
        digest = hmac.new(clave, candidato.to_bytes(8, 'big'), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        valor = int.from_bytes(digest[offset:offset + 4], 'big') & 0x7FFFFFFF
        if hmac.compare_digest(f'{valor % 1_000_000:06d}', codigo):
            return True
    return False


class TokenSGRAuthentication(BaseAuthentication):
    """Acepta ``Authorization: Bearer <token>`` (o ``Token <token>``) emitido por /api/v1/token/."""

    palabras = (b'bearer', b'token')

    def authenticate(self, request):
        partes = get_authorization_header(request).split()
        if not partes or partes[0].lower() not in self.palabras:
            return None
        if len(partes) != 2:
            raise AuthenticationFailed('Encabezado Authorization inválido. Usa: Bearer <token>.')
        try:
            token = partes[1].decode('ascii')
        except UnicodeError:
            raise AuthenticationFailed('Token inválido.')

        ahora = timezone.now()
        acceso = TokenAcceso.objects.filter(huella=huella(token), revocado=False, expira_en__gt=ahora).first()
        if not acceso:
            raise AuthenticationFailed('Token inválido, vencido o revocado.')
        usuario = UsuarioSGR.objects.filter(pk=acceso.usuario_id, is_active=True).first()
        if not usuario:
            raise AuthenticationFailed('El usuario ya no está activo en el SGR.')
        if not acceso.ultimo_uso or acceso.ultimo_uso < ahora - timedelta(minutes=5):
            TokenAcceso.objects.filter(pk=acceso.pk).update(ultimo_uso=ahora)
        return usuario, acceso

    def authenticate_header(self, request):
        return 'Bearer realm="api"'
