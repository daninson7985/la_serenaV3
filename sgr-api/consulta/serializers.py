"""Campos que entrega la API. Nunca se exponen contraseñas, secretos 2FA, RUN, teléfonos ni correos de funcionarios."""
from rest_framework import serializers

from consulta import models as m


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------
class SolicitudTokenSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, style={'input_type': 'password'}, trim_whitespace=False)
    codigo_2fa = serializers.CharField(max_length=6, required=False, allow_blank=True,
                                       help_text='Solo si la cuenta tiene verificación en dos pasos.')


class PerfilSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    nombre = serializers.CharField(source='nombre_completo')
    rol = serializers.CharField()
    delegacion = serializers.IntegerField(source='delegacion_id', allow_null=True)
    es_admin = serializers.SerializerMethodField()
    es_coordinador = serializers.BooleanField()
    limitado_a_delegacion = serializers.BooleanField(source='esta_limitado_a_delegacion')

    def get_es_admin(self, obj) -> bool:
        return obj.es_admin()


class RespuestaTokenSerializer(serializers.Serializer):
    token = serializers.CharField()
    tipo = serializers.CharField(default='Bearer')
    expira_en = serializers.DateTimeField()
    usuario = PerfilSerializer()


# ---------------------------------------------------------------------------
# Catálogos
# ---------------------------------------------------------------------------
class DelegacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.DelegacionSGR
        fields = ['id', 'nombre', 'codigo', 'direccion', 'telefono', 'email', 'activo', 'ambito']


class AreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.AreaSGR
        fields = ['id', 'nombre', 'descripcion', 'estado']


class CargoSerializer(serializers.ModelSerializer):
    area_nombre = serializers.ReadOnlyField(source='area.nombre', default=None)

    class Meta:
        model = m.CargoSGR
        fields = ['id', 'codigo', 'nombre', 'descripcion', 'activo', 'area', 'area_nombre']


class PeriodoSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.PeriodoSGR
        fields = [
            'id', 'nombre', 'anio', 'trimestre', 'fecha_inicio', 'fecha_termino', 'dias_computables',
            'cerrado', 'estado', 'umbral_semaforo_verde', 'umbral_semaforo_ambar', 'umbral_colectivo',
            'tope_cumplimiento',
        ]


class ItemSerializer(serializers.ModelSerializer):
    cargo_nombre = serializers.ReadOnlyField(source='cargo.nombre')
    periodo_nombre = serializers.ReadOnlyField(source='periodo.nombre')

    class Meta:
        model = m.ItemSGR
        fields = [
            'id', 'cargo', 'cargo_nombre', 'periodo', 'periodo_nombre', 'nombre_item', 'descripcion',
            'tipo_unidad', 'meta_cuantitativa', 'ponderador', 'unidad_medida', 'activo',
        ]


class CatalogoSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.CatalogoSGR
        fields = ['id', 'codigo', 'nombre', 'area', 'activo']


class TipoActividadSerializer(serializers.ModelSerializer):
    area_nombre = serializers.ReadOnlyField(source='area.nombre')

    class Meta:
        model = m.TipoActividadSGR
        fields = ['id', 'area', 'area_nombre', 'nombre', 'descripcion', 'activo']


class TipoAtencionSocialSerializer(serializers.ModelSerializer):
    area_nombre = serializers.ReadOnlyField(source='area.nombre')

    class Meta:
        model = m.TipoAtencionSocialSGR
        fields = ['id', 'area', 'area_nombre', 'nombre', 'descripcion', 'activo']


class SubatencionSocialSerializer(serializers.ModelSerializer):
    tipo_atencion_nombre = serializers.ReadOnlyField(source='tipo_atencion.nombre')

    class Meta:
        model = m.SubatencionSocialSGR
        fields = ['id', 'tipo_atencion', 'tipo_atencion_nombre', 'nombre', 'descripcion', 'activo']


class ConceptoAjusteSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.ConceptoAjusteSGR
        fields = ['id', 'nombre', 'naturaleza', 'activo']


class RolSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.RolSGR
        fields = ['id', 'nombre_rol', 'descripcion', 'estado', 'permisos']


# ---------------------------------------------------------------------------
# Personas y registros
# ---------------------------------------------------------------------------
class UsuarioSerializer(serializers.ModelSerializer):
    """Sin contraseña, secreto 2FA, RUN, teléfono ni correo."""
    nombre = serializers.ReadOnlyField(source='nombre_completo')
    cargo_nombre = serializers.ReadOnlyField(source='cargo.nombre', default=None)
    delegacion_nombre = serializers.ReadOnlyField(source='delegacion.nombre', default=None)
    area_nombre = serializers.ReadOnlyField(source='area_entidad.nombre', default=None)

    class Meta:
        model = m.UsuarioSGR
        fields = [
            'id', 'username', 'nombre', 'rol', 'is_active', 'cargo', 'cargo_nombre',
            'delegacion', 'delegacion_nombre', 'area_entidad', 'area_nombre',
        ]


class SolicitanteSerializer(serializers.ModelSerializer):
    """Sin RUN, teléfono ni correo."""
    nombre_completo = serializers.ReadOnlyField()

    class Meta:
        model = m.SolicitanteSGR
        fields = ['id', 'nombre', 'apellido', 'nombre_completo', 'tipo_solicitante', 'direccion', 'estado']


class CompromisoSerializer(serializers.ModelSerializer):
    delegacion_nombre = serializers.ReadOnlyField(source='delegacion.nombre')
    responsable_nombre = serializers.ReadOnlyField(source='responsable.nombre_completo')

    class Meta:
        model = m.CompromisoSGR
        fields = [
            'id', 'origen', 'solicitante', 'territorio', 'delegacion', 'delegacion_nombre',
            'responsable', 'responsable_nombre', 'fecha_registro', 'fecha_compromiso',
            'area_apoyo', 'descripcion', 'estado', 'observacion', 'fecha_realizacion',
        ]


class AjusteIncentivoSerializer(serializers.ModelSerializer):
    concepto_nombre = serializers.ReadOnlyField(source='concepto.nombre', default=None)
    funcionario_nombre = serializers.ReadOnlyField(source='funcionario.nombre_completo')
    periodo_nombre = serializers.ReadOnlyField(source='periodo.nombre', default=None)
    efecto_porcentaje = serializers.FloatField(read_only=True)

    class Meta:
        model = m.AjusteIncentivoSGR
        fields = [
            'id', 'concepto', 'concepto_nombre', 'tipo', 'motivo', 'valor_porcentaje', 'efecto_porcentaje',
            'funcionario', 'funcionario_nombre', 'periodo', 'periodo_nombre', 'estado',
            'fecha_registro', 'registrado_por', 'aprobado_por', 'fecha_aprobacion',
        ]


class OrganizacionSerializer(serializers.ModelSerializer):
    delegacion_nombre = serializers.ReadOnlyField(source='delegacion.nombre', default=None)

    class Meta:
        model = m.OrganizacionSGR
        fields = [
            'id', 'nombre', 'domicilio_legal', 'territorio', 'delegacion', 'delegacion_nombre',
            'socios_activos', 'fecha_constitucion', 'numero_registro_pj', 'fecha_inscripcion_registro',
            'registro_dir', 'fila_origen', 'observacion_importacion',
        ]


class RegistroTuboSerializer(serializers.ModelSerializer):
    delegacion_nombre = serializers.ReadOnlyField(source='delegacion.nombre', default=None)

    class Meta:
        model = m.RegistroTuboSGR
        fields = [
            'id', 'hoja', 'fila_origen', 'numero', 'fecha_solicitud', 'actividad', 'interno_externo',
            'solicitante', 'territorio', 'delegacion', 'delegacion_nombre', 'responsable',
            'fecha_compromiso', 'area_apoyo', 'avance_observaciones', 'estatus',
            'codigo_verificacion_foto', 'observacion_importacion',
        ]


class CartaSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.CartaSGR
        fields = [
            'id', 'hoja', 'fila_origen', 'fecha', 'numero', 'para', 'remite', 'fono_contacto',
            'actividad_tema', 'fecha_actividad', 'encargado_seguimiento', 'estado',
            'pronunciamiento', 'derivada_a', 'observacion', 'observacion_importacion',
        ]
