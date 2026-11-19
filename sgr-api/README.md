# API de consulta SGR

API REST **separada** del Sistema de Gestión de Resultados (SGR) de la Municipalidad de La Serena, documentada con **Swagger / OpenAPI 3**.

- Proyecto independiente: su propio servidor, configuración, dependencias y pruebas.
- **Solo lectura**: lee la base de datos del SGR y nunca la modifica.
- **Token por usuario**: cada persona entra con su usuario y contraseña del SGR y ve solo lo que su rol permite.

## Cómo funciona

```
Cliente (frontend, app, Postman, Swagger)
        │  Authorization: Bearer <token>
        ▼
API de consulta SGR (este proyecto, Django REST Framework + drf-spectacular)
   ├── base "default": base propia y pequeña (tokens e intentos de acceso)
   └── base "sgr": base del SGR, SOLO LECTURA
```

La base del SGR se protege en tres niveles:

1. Los modelos del SGR son `managed=False` y su `save()`/`delete()` lanzan error.
2. La conexión se abre en solo lectura (SQLite `mode=ro`; MySQL `SET SESSION TRANSACTION READ ONLY`).
3. En MySQL/MariaDB se usa un usuario de base de datos con permiso `SELECT` únicamente.

Las reglas de visibilidad son las mismas del SGR (`docs/MATRIZ_PERMISOS.md` del SGR).

## Instalación

Requisitos: Python 3.12 o superior y acceso a la base del SGR.

```powershell
cd sgr-api
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edita `.env`:

- `SECRET_KEY`: clave propia de esta API. Genérala con `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
- `SGR_DB_NAME`: ruta al `db.sqlite3` del SGR (por defecto `../BackEnd3-main/backend/db.sqlite3`).
- Para desarrollo local puedes usar `DEBUG=True`.

Luego:

```powershell
python manage.py migrate      # crea solo la base propia de la API (tokens)
python manage.py runserver 127.0.0.1:8002
```

- Swagger UI: <http://127.0.0.1:8002/api/v1/docs/>
- ReDoc: <http://127.0.0.1:8002/api/v1/redoc/>
- Esquema OpenAPI (YAML): <http://127.0.0.1:8002/api/v1/schema/> (también en `docs/openapi.yaml`)

## Uso

1. **Obtener un token**: `POST /api/v1/token/`

   ```json
   {"username": "mi.usuario", "password": "mi contraseña del SGR"}
   ```

   Si la cuenta tiene verificación en dos pasos, la respuesta pide `requires_2fa`: repite la solicitud agregando `"codigo_2fa": "123456"`.

2. **Consultar** con el encabezado `Authorization: Bearer <token>`. En Swagger: botón **Authorize**.
3. **Cerrar sesión**: `POST /api/v1/token/revocar/`.

El token vence en `API_TOKEN_HORAS` (8 h por defecto). Tras `API_MAX_INTENTOS` (5) intentos fallidos, el usuario queda bloqueado `API_BLOQUEO_MINUTOS` (15) minutos. Las cuentas con cambio de contraseña pendiente deben cambiarla primero en el SGR.

Ejemplo con PowerShell:

```powershell
$r = Invoke-RestMethod -Method Post http://127.0.0.1:8002/api/v1/token/ -ContentType "application/json" `
     -Body '{"username":"mi.usuario","password":"..."}'
Invoke-RestMethod http://127.0.0.1:8002/api/v1/organizaciones/?territorio=RURAL -Headers @{Authorization = "Bearer $($r.token)"}
```

## Endpoints (`/api/v1/`)

Todos son `GET` (listado y detalle `/<id>/`), salvo los de autenticación. Los listados vienen paginados: 50 por página, `?page=2`, `?page_size=` hasta 500.

| Grupo | Endpoint | Filtros |
|---|---|---|
| Autenticación | `POST token/`, `POST token/revocar/`, `GET yo/` | — |
| Catálogos | `delegaciones/`, `areas/`, `cargos/`, `periodos/`, `catalogos/`, `conceptos-ajuste/` | — |
| | `items-medicion/` | `cargo`, `periodo` |
| | `tipos-actividad/`, `tipos-atencion-social/` | `area` |
| | `subatenciones-sociales/` | `tipo_atencion` |
| | `roles/` | — |
| Personas | `usuarios/` | `rol`, `delegacion` |
| | `solicitantes/` | `q`, `tipo_solicitante` |
| Tubo de trabajo | `compromisos/` | `estado`, `territorio`, `delegacion`, `responsable` |
| Incentivos | `ajustes-incentivo/` | `estado`, `periodo`, `funcionario` |
| Datos Excel | `organizaciones/` | `q`, `territorio`, `delegacion` |
| | `tubo-excel/` | `q`, `hoja`, `estatus`, `responsable`, `territorio` |
| | `cartas/` | `q`, `hoja`, `estado` |

## Permisos

✅ todo · 🔸 solo su ámbito · ❌ sin acceso (403)

| Endpoint | Administrador | Coordinador | Delegado | Funcionario | Consulta |
|---|---|---|---|---|---|
| Catálogos | ✅ | ✅ | ✅ | ✅ | ✅ |
| `roles/` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `usuarios/` | ✅ | ✅ | 🔸 su delegación | 🔸 su ficha | ✅ ¹ |
| `solicitantes/` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `compromisos/` | ✅ | ✅ | 🔸 su delegación | 🔸 asignados o creados por él | ✅ ¹ |
| `ajustes-incentivo/` | ✅ | ✅ | ❌ | 🔸 los suyos | ❌ |
| `organizaciones/`, `tubo-excel/` | ✅ | ✅ | 🔸 su delegación | 🔸 su delegación | ✅ ¹ |
| `cartas/` | ✅ | ✅ | vacío | vacío | ✅ ¹ |

¹ Un Usuario de consulta con delegación asignada ve solo la suya.

No se exponen: contraseñas, secretos de verificación en dos pasos, RUN, teléfonos ni correos de funcionarios y solicitantes. Tampoco actividades, evidencias ni casos sociales, que contienen los datos personales más sensibles.

## Despliegue con la base MySQL/MariaDB del SGR (AWS)

1. Crea un usuario de base de datos **solo lectura** para la API:

   ```sql
   CREATE USER 'sgr_api'@'localhost' IDENTIFIED BY 'CONTRASEÑA_LARGA';
   GRANT SELECT ON matriz_sgr_db.* TO 'sgr_api'@'localhost';
   ```

2. En `.env`: `SGR_DB_ENGINE=mysql`, `SGR_DB_NAME`, `SGR_DB_USER=sgr_api`, `SGR_DB_PASSWORD`, `DEBUG=False`, `ALLOWED_HOSTS` con la IP o el dominio, `SECURE_SSL_REDIRECT=True` y `TRUST_PROXY_SSL_HEADER=True` detrás de Nginx con HTTPS.
3. `pip install mysqlclient==2.3.0`, `python manage.py migrate`, `python manage.py collectstatic --noinput` y servir con Gunicorn detrás de Nginx, igual que el SGR.

## Pruebas

```powershell
python manage.py test consulta
```

Las pruebas crean bases temporales: nunca tocan la base real del SGR.

## Mantención

Si el SGR cambia sus tablas o sus reglas de rol, actualiza `consulta/models.py`: los modelos `...SGR` y `PERMISOS_PREDETERMINADOS_POR_ROL` deben coincidir con `sgr_app/models.py`.

## Seguridad

- No subas `.env`, `*.sqlite3` ni exportaciones de datos a GitHub (ya están en `.gitignore`).
- Cada token se guarda solo como huella SHA-256; si la base de la API se filtra, los tokens no se pueden reutilizar.
- Los intentos de acceso quedan registrados en la tabla `IntentoAcceso` de la base propia.
