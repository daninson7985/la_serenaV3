"""Modelos de la API.

- Modelos ``...SGR``: reflejan tablas de la base del SGR. Son de solo lectura
  (``managed=False``): la API nunca crea, modifica ni borra esas tablas o filas.
  Solo declaran las columnas que la API necesita.
- ``TokenAcceso`` e ``IntentoAcceso``: viven en la base propia de la API.
"""
from functools import cached_property

from django.core.exceptions import PermissionDenied
from django.db import models

# Copia de sgr_app.models.PERMISOS_PREDETERMINADOS_POR_ROL (mantener sincronizado).
PERMISOS_PREDETERMINADOS_POR_ROL = {
    'COORDINADOR': ('CREAR_META', 'APROBAR_EVIDENCIA', 'VER_DASHBOARD', 'GESTIONAR_COORDINACION'),
    'DELEGADO': ('CREAR_META', 'APROBAR_EVIDENCIA', 'VER_DASHBOARD', 'GESTIONAR_DELEGACION'),
    'FUNCIONARIO': ('REGISTRAR_ACTIVIDAD', 'VER_DASHBOARD'),
    'CONSULTA': ('VER_DASHBOARD',),
}


def _fk(modelo, **kwargs):
    """Clave foránea de solo lectura entre tablas del SGR (sin restricciones propias)."""
    return models.ForeignKey(
        modelo, on_delete=models.DO_NOTHING, db_constraint=False, related_name='+', **kwargs,
    )


class ModeloSGR(models.Model):
    """Base de los modelos que leen la base del SGR: impide cualquier escritura."""

    class Meta:
        abstract = True
        managed = False

    def save(self, *args, **kwargs):
        raise PermissionDenied('La API de consulta no modifica la base del SGR.')

    def delete(self, *args, **kwargs):
        raise PermissionDenied('La API de consulta no modifica la base del SGR.')


# ---------------------------------------------------------------------------
# Catálogos y estructura
# ---------------------------------------------------------------------------
class DelegacionSGR(ModeloSGR):
    nombre = models.CharField(max_length=100)
    codigo = models.CharField(max_length=10)
    direccion = models.CharField(max_length=255, null=True)
    telefono = models.CharField(max_length=50, null=True)
    email = models.CharField(max_length=254, null=True)
    activo = models.BooleanField()
    ambito = models.CharField(max_length=100)

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_delegacion'
        ordering = ['nombre']


class AreaSGR(ModeloSGR):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(null=True)
    estado = models.BooleanField()

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_area'
        ordering = ['nombre']


class CargoSGR(ModeloSGR):
    codigo = models.CharField(max_length=12)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(null=True)
    activo = models.BooleanField()
    area = _fk(AreaSGR, null=True)

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_cargo'
        ordering = ['nombre']


class RolSGR(ModeloSGR):
    nombre_rol = models.CharField(max_length=50)
    descripcion = models.TextField(null=True)
    estado = models.BooleanField()
    permisos = models.JSONField(default=list)

    class Meta(ModeloSGR.Meta):
        db_table = 'Roles'
        ordering = ['nombre_rol']

    def tiene_permiso(self, codigo):
        """Igual que sgr_app.models.Rol.tienePermiso."""
        if not self.estado:
            return False
        nombre = self.nombre_rol.upper()
        if nombre == 'ADMINISTRADOR':
            return True
        permisos = set(PERMISOS_PREDETERMINADOS_POR_ROL.get(nombre, ())) | set(self.permisos or ())
        return codigo.upper() in permisos


class UsuarioSGR(ModeloSGR):
    """Funcionario del SGR. Reproduce las reglas de rol de sgr_app.models.Usuario."""
    password = models.CharField(max_length=128)
    username = models.CharField(max_length=150)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    is_superuser = models.BooleanField()
    is_active = models.BooleanField()
    rol = models.CharField(max_length=20)
    requires_2fa = models.BooleanField()
    totp_secret = models.CharField(max_length=64, null=True)
    must_change_password = models.BooleanField()
    cargo = _fk(CargoSGR, null=True)
    delegacion = _fk(DelegacionSGR, null=True)
    area_entidad = _fk(AreaSGR, null=True)

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_usuario'
        ordering = ['first_name', 'last_name', 'username']

    # Django REST Framework trata este objeto como el usuario autenticado.
    is_authenticated = True
    is_anonymous = False

    def __str__(self):
        return self.nombre_completo

    @property
    def nombre_completo(self) -> str:
        return f'{self.first_name} {self.last_name}'.strip() or self.username

    @cached_property
    def roles_adicionales(self):
        ids = UsuarioRolSGR.objects.filter(usuario_id=self.pk).values_list('rol_id', flat=True)
        return list(RolSGR.objects.filter(pk__in=list(ids), estado=True))

    def tiene_permiso(self, codigo):
        codigo = codigo.upper()
        if self.is_superuser or self.rol == 'ADMINISTRADOR':
            return True
        if codigo in PERMISOS_PREDETERMINADOS_POR_ROL.get(self.rol, ()):
            return True
        return any(rol.tiene_permiso(codigo) for rol in self.roles_adicionales)

    def es_admin(self):
        return self.tiene_permiso('ACCESO_ADMINISTRADOR')

    @property
    def es_delegado(self):
        return self.rol == 'DELEGADO'

    @property
    def es_coordinador(self):
        return self.tiene_permiso('GESTIONAR_COORDINACION') and not self.es_delegado

    @property
    def es_consulta(self):
        return self.rol == 'CONSULTA' and not self.is_superuser

    @property
    def esta_limitado_a_delegacion(self):
        if self.rol == 'CONSULTA':
            return bool(self.delegacion_id)
        return self.es_delegado or (
            self.tiene_permiso('GESTIONAR_DELEGACION')
            and not self.tiene_permiso('GESTIONAR_COORDINACION')
            and not self.es_admin()
        )

    @property
    def es_funcionario(self):
        return (
            self.rol == 'FUNCIONARIO'
            and not self.es_admin()
            and not self.es_coordinador
            and not self.esta_limitado_a_delegacion
        )


class UsuarioRolSGR(ModeloSGR):
    usuario = _fk(UsuarioSGR)
    rol = _fk(RolSGR)

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_usuario_roles'


class PeriodoSGR(ModeloSGR):
    nombre = models.CharField(max_length=100)
    anio = models.PositiveSmallIntegerField(null=True)
    trimestre = models.PositiveSmallIntegerField(null=True)
    fecha_inicio = models.DateField()
    fecha_termino = models.DateField()
    dias_computables = models.IntegerField()
    cerrado = models.BooleanField()
    estado = models.BooleanField()
    umbral_semaforo_verde = models.FloatField()
    umbral_semaforo_ambar = models.FloatField()
    umbral_colectivo = models.FloatField()
    tope_cumplimiento = models.FloatField()

    class Meta(ModeloSGR.Meta):
        db_table = 'Periodos'
        ordering = ['-fecha_inicio']


class ItemSGR(ModeloSGR):
    cargo = _fk(CargoSGR)
    periodo = _fk(PeriodoSGR)
    nombre_item = models.CharField(max_length=150)
    descripcion = models.TextField(null=True)
    tipo_unidad = models.CharField(max_length=20)
    meta_cuantitativa = models.FloatField()
    ponderador = models.FloatField()
    unidad_medida = models.CharField(max_length=50)
    activo = models.BooleanField()

    class Meta(ModeloSGR.Meta):
        db_table = 'Items'
        ordering = ['cargo_id', 'nombre_item']


class CatalogoSGR(ModeloSGR):
    codigo = models.CharField(max_length=30)
    nombre = models.CharField(max_length=150)
    area = models.CharField(max_length=100, null=True)
    activo = models.BooleanField()

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_catalogoservicio'
        ordering = ['codigo']


class TipoActividadSGR(ModeloSGR):
    area = _fk(AreaSGR)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField()
    activo = models.BooleanField()

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_tipoactividad'
        ordering = ['nombre']


class TipoAtencionSocialSGR(ModeloSGR):
    area = _fk(AreaSGR)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField()
    activo = models.BooleanField()

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_tipoatencionsocial'
        ordering = ['nombre']


class SubatencionSocialSGR(ModeloSGR):
    tipo_atencion = _fk(TipoAtencionSocialSGR)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField()
    activo = models.BooleanField()

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_subatencionsocial'
        ordering = ['tipo_atencion_id', 'nombre']


class ConceptoAjusteSGR(ModeloSGR):
    nombre = models.CharField(max_length=100)
    naturaleza = models.CharField(max_length=10)
    activo = models.BooleanField()

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_conceptoajuste'
        ordering = ['nombre']


# ---------------------------------------------------------------------------
# Registros operativos
# ---------------------------------------------------------------------------
class SolicitanteSGR(ModeloSGR):
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    tipo_solicitante = models.CharField(max_length=30)
    direccion = models.CharField(max_length=255, null=True)
    estado = models.BooleanField()

    class Meta(ModeloSGR.Meta):
        db_table = 'Solicitantes'
        ordering = ['nombre', 'apellido', 'id']

    @property
    def nombre_completo(self) -> str:
        return f'{self.nombre} {self.apellido}'.strip()


class CompromisoSGR(ModeloSGR):
    origen = models.CharField(max_length=100)
    solicitante = models.CharField(max_length=150)
    territorio = models.CharField(max_length=150)
    delegacion = _fk(DelegacionSGR)
    responsable = _fk(UsuarioSGR)
    creado_por = _fk(UsuarioSGR, null=True)
    fecha_registro = models.DateTimeField()
    fecha_compromiso = models.DateField()
    fecha_comprometida = models.DateField()
    area_apoyo = models.CharField(max_length=150)
    descripcion = models.TextField()
    estado = models.CharField(max_length=30)
    observacion = models.TextField(null=True)
    fecha_realizacion = models.DateTimeField(null=True)
    anulado = models.BooleanField()

    class Meta(ModeloSGR.Meta):
        db_table = 'Compromisos'
        ordering = ['fecha_compromiso', 'id']


class AjusteIncentivoSGR(ModeloSGR):
    tipo = models.CharField(max_length=100)
    concepto = _fk(ConceptoAjusteSGR, null=True)
    motivo = models.TextField()
    valor_porcentaje = models.FloatField()
    fecha_registro = models.DateTimeField()
    funcionario = _fk(UsuarioSGR)
    registrado_por = _fk(UsuarioSGR, null=True)
    periodo = _fk(PeriodoSGR, null=True)
    estado = models.CharField(max_length=20)
    aprobado_por = _fk(UsuarioSGR, null=True, db_column='aprobadoPor_id')
    fecha_aprobacion = models.DateTimeField(null=True, db_column='fechaAprobacion')

    class Meta(ModeloSGR.Meta):
        db_table = 'AjustesIncentivo'
        ordering = ['-fecha_registro', '-id']

    @property
    def efecto_porcentaje(self) -> float:
        """Igual que AjusteIncentivo.aplicar_ajuste(): negativo si el concepto es NEGATIVO."""
        impacto = abs(self.valor_porcentaje)
        if self.concepto_id:
            negativo = self.concepto.naturaleza == 'NEGATIVO'
        else:
            negativo = self.tipo in {'PENALIZACION', 'DESCUENTO'}
        return -impacto if negativo else impacto


class OrganizacionSGR(ModeloSGR):
    nombre = models.CharField(max_length=255)
    domicilio_legal = models.CharField(max_length=255)
    territorio = models.CharField(max_length=50)
    delegacion = _fk(DelegacionSGR, null=True)
    socios_activos = models.PositiveIntegerField(null=True)
    fecha_constitucion = models.DateField(null=True)
    numero_registro_pj = models.CharField(max_length=30)
    fecha_inscripcion_registro = models.DateField(null=True)
    registro_dir = models.CharField(max_length=30)
    fila_origen = models.PositiveIntegerField()
    observacion_importacion = models.TextField()

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_organizacioncomunitaria'
        ordering = ['nombre', 'id']


class RegistroTuboSGR(ModeloSGR):
    hoja = models.CharField(max_length=50)
    fila_origen = models.PositiveIntegerField()
    numero = models.PositiveIntegerField(null=True)
    fecha_solicitud = models.DateField(null=True)
    actividad = models.TextField()
    interno_externo = models.CharField(max_length=30)
    solicitante = models.CharField(max_length=255)
    territorio = models.CharField(max_length=100)
    delegacion = _fk(DelegacionSGR, null=True)
    responsable = models.CharField(max_length=150)
    fecha_compromiso = models.DateField(null=True)
    area_apoyo = models.CharField(max_length=255)
    avance_observaciones = models.TextField()
    estatus = models.CharField(max_length=50)
    codigo_verificacion_foto = models.CharField(max_length=100)
    observacion_importacion = models.TextField()

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_registrotubotrabajo'
        ordering = ['hoja', 'fila_origen']


class CartaSGR(ModeloSGR):
    hoja = models.CharField(max_length=50)
    fila_origen = models.PositiveIntegerField()
    fecha = models.DateField(null=True)
    numero = models.CharField(max_length=30)
    para = models.CharField(max_length=150)
    remite = models.CharField(max_length=255)
    fono_contacto = models.CharField(max_length=50)
    actividad_tema = models.TextField()
    fecha_actividad = models.DateField(null=True)
    encargado_seguimiento = models.CharField(max_length=150)
    estado = models.CharField(max_length=50)
    pronunciamiento = models.CharField(max_length=50)
    derivada_a = models.CharField(max_length=150)
    observacion = models.TextField()
    observacion_importacion = models.TextField()

    class Meta(ModeloSGR.Meta):
        db_table = 'sgr_app_cartaseguimiento'
        ordering = ['hoja', 'fila_origen']


# ---------------------------------------------------------------------------
# Base propia de la API
# ---------------------------------------------------------------------------
class TokenAcceso(models.Model):
    """Token emitido a un usuario del SGR. Se guarda solo su huella SHA-256, nunca el token."""
    huella = models.CharField(max_length=64, unique=True)
    usuario_id = models.BigIntegerField(db_index=True)
    username = models.CharField(max_length=150)
    creado_en = models.DateTimeField(auto_now_add=True)
    expira_en = models.DateTimeField()
    revocado = models.BooleanField(default=False)
    ultimo_uso = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Token de acceso'
        verbose_name_plural = 'Tokens de acceso'


class IntentoAcceso(models.Model):
    """Registro de inicios de sesión en la API (exitosos y fallidos) para auditoría y bloqueo."""
    username = models.CharField(max_length=150, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    exitoso = models.BooleanField()
    motivo = models.CharField(max_length=100, blank=True, default='')
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Intento de acceso'
        verbose_name_plural = 'Intentos de acceso'
