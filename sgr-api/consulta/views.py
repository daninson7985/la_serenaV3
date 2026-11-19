"""Endpoints de la API (todos de solo lectura salvo la emisión y revocación de tokens).

Las reglas de visibilidad replican las del SGR (sgr_app/views.py y docs/MATRIZ_PERMISOS.md):
- Administrador y Coordinador: toda la comuna.
- Delegado (y Consulta con delegación): solo su delegación.
- Funcionario: sus propios registros o los de su delegación, según el recurso.
"""
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView

from consulta import models as m
from consulta import serializers as s
from consulta.autenticacion import codigo_totp_valido, huella

registro = logging.getLogger('sgr_api.acceso')
_HASH_FICTICIO = make_password('contraseña-que-nadie-usa')


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------
def _ip(request):
    return request.META.get('REMOTE_ADDR')


def _registrar(username, request, exitoso, motivo=''):
    m.IntentoAcceso.objects.create(username=username[:150], ip=_ip(request), exitoso=exitoso, motivo=motivo)
    registro.info('Token %s: usuario=%r ip=%s %s', 'emitido' if exitoso else 'rechazado', username, _ip(request), motivo)


class ObtenerTokenView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle, ScopedRateThrottle]
    throttle_scope = 'token'

    @extend_schema(
        tags=['Autenticación'],
        summary='Obtener token',
        description=(
            'Intercambia usuario y contraseña del SGR por un token. Si la cuenta tiene verificación en '
            'dos pasos, envía también `codigo_2fa`. Tras varios intentos fallidos el usuario queda '
            'bloqueado unos minutos (respuesta 429).'
        ),
        request=s.SolicitudTokenSerializer,
        responses={
            200: s.RespuestaTokenSerializer,
            401: OpenApiResponse(description='Credenciales o código 2FA incorrectos (o falta el código).'),
            403: OpenApiResponse(description='La cuenta debe cambiar su contraseña en el SGR.'),
            429: OpenApiResponse(description='Usuario bloqueado temporalmente por intentos fallidos.'),
        },
    )
    def post(self, request):
        datos = s.SolicitudTokenSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        username = datos.validated_data['username'].strip()
        clave = datos.validated_data['password']
        codigo = (datos.validated_data.get('codigo_2fa') or '').strip()

        desde = timezone.now() - timedelta(minutes=settings.API_BLOQUEO_MINUTOS)
        fallidos = m.IntentoAcceso.objects.filter(username__iexact=username, exitoso=False, fecha__gte=desde).count()
        if fallidos >= settings.API_MAX_INTENTOS:
            _registrar(username, request, False, 'bloqueado')
            return Response(
                {'detail': f'Demasiados intentos fallidos. Intenta de nuevo en {settings.API_BLOQUEO_MINUTOS} minutos.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        usuario = m.UsuarioSGR.objects.filter(username__iexact=username).first()
        # Se verifica un hash aunque el usuario no exista, para no revelar qué cuentas existen.
        clave_ok = check_password(clave, usuario.password if usuario else _HASH_FICTICIO)
        if not usuario or not clave_ok or not usuario.is_active:
            _registrar(username, request, False, 'credenciales')
            return Response({'detail': 'Usuario o contraseña incorrectos.'}, status=status.HTTP_401_UNAUTHORIZED)

        if usuario.must_change_password:
            _registrar(username, request, False, 'cambio de contraseña pendiente')
            return Response({'detail': 'Debes cambiar tu contraseña en el SGR antes de usar la API.'},
                            status=status.HTTP_403_FORBIDDEN)

        if usuario.requires_2fa:
            if not codigo:
                return Response({'detail': 'Tu cuenta requiere el código de verificación en dos pasos.',
                                 'requires_2fa': True}, status=status.HTTP_401_UNAUTHORIZED)
            if not codigo_totp_valido(usuario.totp_secret, codigo):
                _registrar(username, request, False, 'código 2FA')
                return Response({'detail': 'Código de verificación incorrecto.', 'requires_2fa': True},
                                status=status.HTTP_401_UNAUTHORIZED)

        token = secrets.token_urlsafe(32)
        expira = timezone.now() + timedelta(hours=settings.API_TOKEN_HORAS)
        m.TokenAcceso.objects.create(huella=huella(token), usuario_id=usuario.pk, username=usuario.username, expira_en=expira)
        _registrar(usuario.username, request, True)
        return Response({
            'token': token,
            'tipo': 'Bearer',
            'expira_en': expira,
            'usuario': s.PerfilSerializer(usuario).data,
        })


class RevocarTokenView(APIView):
    @extend_schema(tags=['Autenticación'], summary='Cerrar sesión (revocar el token actual)',
                   request=None, responses={204: None})
    def post(self, request):
        m.TokenAcceso.objects.filter(pk=request.auth.pk).update(revocado=True)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PerfilView(APIView):
    @extend_schema(tags=['Autenticación'], summary='Mi perfil y alcance', responses=s.PerfilSerializer)
    def get(self, request):
        return Response(s.PerfilSerializer(request.user).data)


# ---------------------------------------------------------------------------
# Reglas de alcance
# ---------------------------------------------------------------------------
def _limitado(user):
    """Delegado, Funcionario y Consulta con delegación solo ven su delegación."""
    return user.es_funcionario or user.esta_limitado_a_delegacion


def _por_delegacion(qs, user, campo='delegacion_id'):
    if not _limitado(user):
        return qs
    if not user.delegacion_id:
        return qs.none()
    return qs.filter(**{campo: user.delegacion_id})


def _buscar(qs, texto, campos):
    texto = (texto or '').strip()
    if not texto:
        return qs
    condicion = Q()
    for campo in campos:
        condicion |= Q(**{f'{campo}__icontains': texto})
    return qs.filter(condicion)


def _filtros(params, qs, exactos=(), numericos=()):
    for campo in exactos:
        if params.get(campo):
            qs = qs.filter(**{campo: params[campo]})
    for campo in numericos:
        valor = params.get(campo, '')
        if valor.isdecimal():
            qs = qs.filter(**{f'{campo}_id': valor})
    return qs


def _parametros(*nombres, numericos=(), q=None):
    lista = [OpenApiParameter(n, OpenApiTypes.STR, description=f'Filtra por {n} (valor exacto).') for n in nombres]
    lista += [OpenApiParameter(n, OpenApiTypes.INT, description=f'Filtra por id de {n}.') for n in numericos]
    if q:
        lista.append(OpenApiParameter('q', OpenApiTypes.STR, description=f'Búsqueda de texto en: {q}.'))
    return extend_schema_view(list=extend_schema(parameters=lista))


class Consulta(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]


# ---------------------------------------------------------------------------
# Catálogos (cualquier usuario autenticado)
# ---------------------------------------------------------------------------
@extend_schema_view(list=extend_schema(tags=['Catálogos']), retrieve=extend_schema(tags=['Catálogos']))
class DelegacionViewSet(Consulta):
    """Delegaciones municipales."""
    queryset = m.DelegacionSGR.objects.all()
    serializer_class = s.DelegacionSerializer


@extend_schema_view(list=extend_schema(tags=['Catálogos']), retrieve=extend_schema(tags=['Catálogos']))
class AreaViewSet(Consulta):
    """Áreas funcionales."""
    queryset = m.AreaSGR.objects.all()
    serializer_class = s.AreaSerializer


@extend_schema_view(list=extend_schema(tags=['Catálogos']), retrieve=extend_schema(tags=['Catálogos']))
class CargoViewSet(Consulta):
    """Cargos de los funcionarios."""
    queryset = m.CargoSGR.objects.select_related('area')
    serializer_class = s.CargoSerializer


@extend_schema_view(list=extend_schema(tags=['Catálogos']), retrieve=extend_schema(tags=['Catálogos']))
class PeriodoViewSet(Consulta):
    """Períodos de medición (trimestres)."""
    queryset = m.PeriodoSGR.objects.all()
    serializer_class = s.PeriodoSerializer


@_parametros(numericos=('cargo', 'periodo'))
@extend_schema_view(list=extend_schema(tags=['Catálogos']), retrieve=extend_schema(tags=['Catálogos']))
class ItemViewSet(Consulta):
    """Ítems de medición: meta y ponderador de cada cargo por período."""
    queryset = m.ItemSGR.objects.select_related('cargo', 'periodo')
    serializer_class = s.ItemSerializer

    def get_queryset(self):
        return _filtros(self.request.query_params, super().get_queryset(), numericos=('cargo', 'periodo'))


@extend_schema_view(list=extend_schema(tags=['Catálogos']), retrieve=extend_schema(tags=['Catálogos']))
class CatalogoViewSet(Consulta):
    """Catálogo de servicios."""
    queryset = m.CatalogoSGR.objects.all()
    serializer_class = s.CatalogoSerializer


@_parametros(numericos=('area',))
@extend_schema_view(list=extend_schema(tags=['Catálogos']), retrieve=extend_schema(tags=['Catálogos']))
class TipoActividadViewSet(Consulta):
    """Tipos de actividad por área."""
    queryset = m.TipoActividadSGR.objects.select_related('area')
    serializer_class = s.TipoActividadSerializer

    def get_queryset(self):
        return _filtros(self.request.query_params, super().get_queryset(), numericos=('area',))


@_parametros(numericos=('area',))
@extend_schema_view(list=extend_schema(tags=['Catálogos']), retrieve=extend_schema(tags=['Catálogos']))
class TipoAtencionSocialViewSet(Consulta):
    """Tipos de atención social."""
    queryset = m.TipoAtencionSocialSGR.objects.select_related('area')
    serializer_class = s.TipoAtencionSocialSerializer

    def get_queryset(self):
        return _filtros(self.request.query_params, super().get_queryset(), numericos=('area',))


@_parametros(numericos=('tipo_atencion',))
@extend_schema_view(list=extend_schema(tags=['Catálogos']), retrieve=extend_schema(tags=['Catálogos']))
class SubatencionSocialViewSet(Consulta):
    """Subatenciones de cada tipo de atención social."""
    queryset = m.SubatencionSocialSGR.objects.select_related('tipo_atencion')
    serializer_class = s.SubatencionSocialSerializer

    def get_queryset(self):
        return _filtros(self.request.query_params, super().get_queryset(), numericos=('tipo_atencion',))


@extend_schema_view(list=extend_schema(tags=['Catálogos']), retrieve=extend_schema(tags=['Catálogos']))
class ConceptoAjusteViewSet(Consulta):
    """Conceptos de ajuste de incentivo (positivo / negativo)."""
    queryset = m.ConceptoAjusteSGR.objects.all()
    serializer_class = s.ConceptoAjusteSerializer


@extend_schema_view(list=extend_schema(tags=['Catálogos']), retrieve=extend_schema(tags=['Catálogos']))
class RolViewSet(Consulta):
    """Roles adicionales y sus permisos. Solo Administrador y Coordinador."""
    queryset = m.RolSGR.objects.all()
    serializer_class = s.RolSerializer

    def get_queryset(self):
        user = self.request.user
        if not (user.es_admin() or user.es_coordinador):
            raise PermissionDenied('Solo Administrador y Coordinador consultan los roles.')
        return super().get_queryset()


# ---------------------------------------------------------------------------
# Personas y registros operativos
# ---------------------------------------------------------------------------
@_parametros('rol', numericos=('delegacion',))
@extend_schema_view(list=extend_schema(tags=['Personas']), retrieve=extend_schema(tags=['Personas']))
class UsuarioViewSet(Consulta):
    """Funcionarios (sin datos de contacto). El Funcionario ve solo su ficha; el Delegado, su delegación."""
    queryset = m.UsuarioSGR.objects.select_related('cargo', 'delegacion', 'area_entidad')
    serializer_class = s.UsuarioSerializer

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.es_funcionario:
            qs = qs.filter(pk=user.pk)
        elif user.esta_limitado_a_delegacion:
            qs = qs.filter(delegacion_id=user.delegacion_id)
        return _filtros(self.request.query_params, qs, exactos=('rol',), numericos=('delegacion',))


@_parametros('tipo_solicitante', q='nombre, apellido, dirección')
@extend_schema_view(list=extend_schema(tags=['Personas']), retrieve=extend_schema(tags=['Personas']))
class SolicitanteViewSet(Consulta):
    """Solicitantes activos (sin RUN, teléfono ni correo). No disponible para el Usuario de consulta."""
    queryset = m.SolicitanteSGR.objects.filter(estado=True)
    serializer_class = s.SolicitanteSerializer

    def get_queryset(self):
        if self.request.user.es_consulta:
            raise PermissionDenied('El usuario de consulta no tiene acceso a los solicitantes.')
        params = self.request.query_params
        qs = _buscar(super().get_queryset(), params.get('q'), ['nombre', 'apellido', 'direccion'])
        return _filtros(params, qs, exactos=('tipo_solicitante',))


@_parametros('estado', 'territorio', numericos=('delegacion', 'responsable'))
@extend_schema_view(list=extend_schema(tags=['Tubo de trabajo']), retrieve=extend_schema(tags=['Tubo de trabajo']))
class CompromisoViewSet(Consulta):
    """Compromisos vigentes del Tubo de Trabajo (los anulados no se muestran)."""
    queryset = m.CompromisoSGR.objects.filter(anulado=False).select_related('delegacion', 'responsable')
    serializer_class = s.CompromisoSerializer

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.esta_limitado_a_delegacion:
            qs = qs.filter(delegacion_id=user.delegacion_id)
        elif user.es_funcionario:
            qs = qs.filter(Q(responsable_id=user.pk) | Q(creado_por_id=user.pk))
        return _filtros(self.request.query_params, qs, exactos=('estado', 'territorio'),
                        numericos=('delegacion', 'responsable'))


@_parametros('estado', numericos=('periodo', 'funcionario'))
@extend_schema_view(list=extend_schema(tags=['Incentivos']), retrieve=extend_schema(tags=['Incentivos']))
class AjusteIncentivoViewSet(Consulta):
    """Incentivos y penalizaciones. Administrador y Coordinador ven todos; el Funcionario, los suyos."""
    queryset = m.AjusteIncentivoSGR.objects.select_related('concepto', 'funcionario', 'periodo')
    serializer_class = s.AjusteIncentivoSerializer

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user.es_admin() or user.es_coordinador:
            pass
        elif user.es_funcionario:
            qs = qs.filter(funcionario_id=user.pk)
        else:
            raise PermissionDenied('No tienes acceso a los ajustes de incentivo.')
        return _filtros(self.request.query_params, qs, exactos=('estado',), numericos=('periodo', 'funcionario'))


# ---------------------------------------------------------------------------
# Datos importados de los Excel
# ---------------------------------------------------------------------------
@_parametros('territorio', numericos=('delegacion',), q='nombre, domicilio')
@extend_schema_view(list=extend_schema(tags=['Datos Excel']), retrieve=extend_schema(tags=['Datos Excel']))
class OrganizacionViewSet(Consulta):
    """Organizaciones comunitarias (Excel JJVV)."""
    queryset = m.OrganizacionSGR.objects.select_related('delegacion')
    serializer_class = s.OrganizacionSerializer

    def get_queryset(self):
        params = self.request.query_params
        qs = _por_delegacion(super().get_queryset(), self.request.user)
        qs = _buscar(qs, params.get('q'), ['nombre', 'domicilio_legal'])
        return _filtros(params, qs, exactos=('territorio',), numericos=('delegacion',))


@_parametros('hoja', 'estatus', 'responsable', 'territorio', q='actividad, solicitante, avance, área de apoyo')
@extend_schema_view(list=extend_schema(tags=['Datos Excel']), retrieve=extend_schema(tags=['Datos Excel']))
class RegistroTuboViewSet(Consulta):
    """Registros del tubo de trabajo tal como vienen en la matriz Excel."""
    queryset = m.RegistroTuboSGR.objects.select_related('delegacion')
    serializer_class = s.RegistroTuboSerializer

    def get_queryset(self):
        params = self.request.query_params
        qs = _por_delegacion(super().get_queryset(), self.request.user)
        qs = _buscar(qs, params.get('q'), ['actividad', 'solicitante', 'avance_observaciones', 'area_apoyo'])
        return _filtros(params, qs, exactos=('hoja', 'estatus', 'responsable', 'territorio'))


@_parametros('hoja', 'estado', q='remite, para, tema, observación')
@extend_schema_view(list=extend_schema(tags=['Datos Excel']), retrieve=extend_schema(tags=['Datos Excel']))
class CartaViewSet(Consulta):
    """Cartas de la matriz Excel. No tienen delegación: solo las ven perfiles sin límite territorial."""
    queryset = m.CartaSGR.objects.all()
    serializer_class = s.CartaSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if _limitado(self.request.user):
            return qs.none()
        params = self.request.query_params
        qs = _buscar(qs, params.get('q'), ['remite', 'para', 'actividad_tema', 'observacion'])
        return _filtros(params, qs, exactos=('hoja', 'estado'))
