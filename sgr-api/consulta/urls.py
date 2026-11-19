from django.urls import include, path
from rest_framework.routers import DefaultRouter

from consulta import views as v

router = DefaultRouter()
# Catálogos
router.register(r'delegaciones', v.DelegacionViewSet)
router.register(r'areas', v.AreaViewSet)
router.register(r'cargos', v.CargoViewSet)
router.register(r'periodos', v.PeriodoViewSet)
router.register(r'items-medicion', v.ItemViewSet)
router.register(r'catalogos', v.CatalogoViewSet)
router.register(r'tipos-actividad', v.TipoActividadViewSet)
router.register(r'tipos-atencion-social', v.TipoAtencionSocialViewSet)
router.register(r'subatenciones-sociales', v.SubatencionSocialViewSet)
router.register(r'conceptos-ajuste', v.ConceptoAjusteViewSet)
router.register(r'roles', v.RolViewSet)
# Personas y registros
router.register(r'usuarios', v.UsuarioViewSet)
router.register(r'solicitantes', v.SolicitanteViewSet)
router.register(r'compromisos', v.CompromisoViewSet)
router.register(r'ajustes-incentivo', v.AjusteIncentivoViewSet)
# Datos importados de los Excel
router.register(r'organizaciones', v.OrganizacionViewSet)
router.register(r'tubo-excel', v.RegistroTuboViewSet)
router.register(r'cartas', v.CartaViewSet)

urlpatterns = [
    path('token/', v.ObtenerTokenView.as_view(), name='token'),
    path('token/revocar/', v.RevocarTokenView.as_view(), name='token_revocar'),
    path('yo/', v.PerfilView.as_view(), name='perfil'),
    path('', include(router.urls)),
]
