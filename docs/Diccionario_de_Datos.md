# Diccionario de Datos — Base de datos del Sistema de Bitácoras Pesqueras

**Motor:** PostgreSQL (Supabase) · **Esquema:** `public` · **Fuente autoritativa:** las
migraciones SQL de `supabase-backend/migrations/` (0001–0016). Este documento se generó a
partir de ellas al 2026-07-09.

**Convenciones generales:**

- Llaves primarias **UUID v4** en todas las tablas (generadas en el cliente para soportar
  captura offline; `DEFAULT uuid_generate_v4()` en el servidor).
- Nombres en **snake_case en español**. Catálogos con prefijo `cat_`.
- Geometrías en **WGS-84 (EPSG:4326)** vía PostGIS.
- Las migraciones son **append-only**: nunca se edita una aplicada; la tabla interna
  `_migrations` registra cuáles ya corrieron.

---

## 1. Tipos enumerados (ENUM)

| Tipo | Valores | Uso |
|---|---|---|
| `tipo_registro_enum` | MASIVO, BITACORA | Origen del registro de faena. **MASIVO** = muestreo por monitoreo externo; **BITACORA** = registro completo del pescador. ⚠️ No sumar entre tipos. |
| `procesado_enum` | ENTERO, EVISCERADO, NA | Cómo estaba el organismo al pesarlo (interpreta `peso_gr`) |
| `sexo_enum` | MACHO, HEMBRA, INDETERMINADO, NA | Sexo del organismo medido |
| `madurez_nikolsky_enum` | NA, 1–6 | Escala Nikolsky de madurez gonádica (CM-07) |
| `origen_carnada_enum` | COMPRADA, PESCADA, NA | Origen de la carnada |
| `tipo_lugar_muestreo_enum` | PESCADERIA, PARAJE, ND | Tipo de lugar de desembarque de la comunidad |
| `tipo_dato_campo_enum` | TEXT, NUMERIC, BOOLEAN, DATE, TIME, SELECT | Tipo de dato de un campo personalizado |
| `grupo_taxonomico_enum` | PEZ, … | Grupo taxonómico de la especie |
| `estado_catalogo_enum` | pendiente, aprobado, rechazado, fusionado | Ciclo de vida de una entrada de catálogo (migración 0003) |
| `estado_formulario_enum` | borrador, publicado, archivado | Ciclo de vida de una versión de formulario (0002) |
| `rol_usuario_enum` | TECNICO, ADMINISTRADOR, ANALISTA | Rol de usuario para permisos/RLS (0004) |

---

## 2. Catálogos (`cat_*`)

**Columnas comunes** (presentes en los catálogos curables): `id UUID PK`,
`nombre TEXT` (único, solo o en combinación), `es_aprobado BOOLEAN DEFAULT FALSE`
(bandera de visibilidad en la app: solo lo aprobado aparece en selectores). La migración
0003 añadió a todos ellos el ciclo de vida de propuestas: `estado estado_catalogo_enum
DEFAULT 'pendiente'`, `propuesto_por UUID` (usuario que propuso) y `propuesto_at
TIMESTAMPTZ`. Invariante: `es_aprobado = (estado = 'aprobado')`.

| Tabla | Propósito | Columnas propias (además de las comunes) |
|---|---|---|
| `cat_formato_origen` | Formato/fuente de captura (SURVEY123, BOCA_ALAMO, CM05, CM07, NOTA_PAGO, DEPRECADO, MASIVOS_LEGACY, BITACORA_LEGACY) | `codigo TEXT UNIQUE` (slug), `descripcion`, `activo BOOLEAN` |
| `cat_region` | Región geográfica (Golfo de California, Pacífico, Nayarit) | `descripcion`, `activo`, `created_at` |
| `cat_zona_pesca` | Zona de pesca (Corredor sur/norte, Bahía de La Paz, PNAES, Cerralvo, Pacífico) | `region_id → cat_region`, `limite GEOMETRY(MultiPolygon,4326)` (permite asignación automática por `ST_Within`) |
| `cat_area_pesca` | Área dentro de una zona (ej. CS-Rodadero a El Morrito) | `zona_pesca_id → cat_zona_pesca (NOT NULL)`, `limite MultiPolygon`; UNIQUE(zona, nombre) |
| `cat_sitio_pesca` | Sitio específico (ej. El Mechudo) | `area_pesca_id → cat_area_pesca`, `ubicacion GEOMETRY(Point,4326)` (NULL solo en históricos); UNIQUE(área, nombre) |
| `cat_comunidad` | Comunidad pesquera / lugar de muestreo | `tipo_lugar_muestreo_enum DEFAULT 'ND'` |
| `cat_cooperativa` | Cooperativa pesquera | `rfc TEXT` |
| `cat_embarcacion` | Embarcación | `cooperativa_id → cat_cooperativa`; UNIQUE(cooperativa, nombre) |
| `cat_pescador` | Pescador (capitán de faena o pescador individual) | `cooperativa_id → cat_cooperativa`; UNIQUE(nombre, cooperativa) |
| `cat_tecnico` | Técnico de campo | `iniciales TEXT` (las de "Datos capturados por" del Anexo 2) |
| `cat_especie` | Especie (peces y otros grupos) | `nombre_comun`, `nombre_cientifico DEFAULT 'Pendiente'`, `grupo_taxonomico_enum`, `es_etp BOOLEAN` (En peligro/Amenazada/Protegida), `apta_carnada BOOLEAN`, `longitud_maxima_cm NUMERIC` (0009 — umbral para marcar tallas sospechosas); UNIQUE(nombre_comun, nombre_cientifico) |
| `cat_tipo_arte` | Arte de pesca (Piola, Chinchorro, Red, Trampa, Cimbra) | — |
| `cat_tipo_anzuelo` | Tipo de anzuelo (Noruego, Circular, Japonés, Kahle) | — |
| `cat_tipo_operacion` | Operación del arte (Fondo, Media agua, Aboyado…) | — |
| `cat_tipo_gasto` | Concepto de gasto (Gasolina, Aceite, Anzuelos, Hielo, Otro…) | sin `es_aprobado` |
| `cat_tipo_fondo` | Tipo de fondo marino | — |
| `cat_tipo_viento` | Condición de viento | sin `es_aprobado` |
| `cat_tipo_luna` | Fase lunar | sin `es_aprobado` |
| `cat_tipo_marea` | Condición de marea | sin `es_aprobado` |
| `cat_tipo_interaccion_etp` | Resultado de interacción con especie protegida | `codigo TEXT UNIQUE`: LIBERADO_SIN_DANO, LIBERADO_CON_DANO, NO_LIBERADO, NO_SOBREVIVIO, OTRO; sin `es_aprobado` |

---

## 3. Entidad central: `faena`

Un viaje/jornada de pesca. Todas las tablas operativas cuelgan de ella
(`ON DELETE CASCADE`).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `id` | UUID | PK | Generado en el cliente (offline-first) |
| `legacy_id` | TEXT | ✓ | ID / Num.Formato / GlobalID original del Anexo 2 (histórico) |
| `codigo_formato` | TEXT | ✓ | Código de formato de origen (texto histórico) |
| `formato_origen_id` | UUID → cat_formato_origen | ✗ | Formato fuente |
| `tipo_registro` | tipo_registro_enum | ✗ | MASIVO / BITACORA (default MASIVO). ⚠️ No sumar entre tipos |
| `fecha` | DATE | ✗ | Fecha de la faena |
| `comunidad_id` | UUID → cat_comunidad | ✗ | Comunidad de desembarque |
| `sitio_pesca_id` | UUID → cat_sitio_pesca | ✗ | Sitio de pesca |
| `area_pesca_id` | UUID → cat_area_pesca | ✓ | Área (derivable del sitio) |
| `zona_pesca_id` | UUID → cat_zona_pesca | ✓ | Zona (derivable del área) |
| `latitud_legacy`, `longitud_legacy` | NUMERIC(9,6) | ✓ | Solo migración histórica; NULL en registros nuevos |
| `embarcacion_id` | UUID → cat_embarcacion | ✓ | Embarcación |
| `cooperativa_id` | UUID → cat_cooperativa | ✓ | Cooperativa |
| `capitan_id` | UUID → cat_pescador | ✗ | Capitán |
| `tecnico_id` | UUID → cat_tecnico | ✗ | Técnico que capturó los datos |
| `encargado_lugar` | TEXT | ✓ | Encargado del lugar de muestreo |
| `num_pescadores` | INT > 0 | ✓ | Número de pescadores |
| `gasolina_lts` | NUMERIC(8,2) ≥ 0 | ✓ | Litros de gasolina |
| `motor_hp` | NUMERIC(6,1) > 0 | ✓ | Potencia del motor |
| `marca_motor` | TEXT | ✓ | Marca del motor |
| `tiempo_efectivo_pesca_h` | NUMERIC(6,2) > 0 | ✗ | **Único campo de tiempo**: horas decimales efectivas operando el arte (consolida los campos de hora del Anexo 2) |
| `dias_efectivos_pesca` | INT | ✓ | Solo CM-05; típicamente 1 |
| `profundidad_min_brazas`, `profundidad_max_brazas` | NUMERIC(6,2) ≥ 0 | ✓ | Profundidad **en brazas**; CHECK max ≥ min |
| `tipo_fondo_id` | UUID → cat_tipo_fondo | ✓ | Tipo de fondo |
| `viento_id`, `luna_id`, `marea_id` | UUID → cat_tipo_* | ✓ | Meteorología |
| `estado_tiempo`, `corriente` | TEXT | ✓ | Condiciones (texto libre) |
| `observaciones` | TEXT | ✓ | Observaciones generales |
| `region_id` | UUID → cat_region | ✓ | Región (propagada desde zona en históricos) |
| `dias_jornada` | INT ≥ 1 | ✓ | Días de la jornada (viajes multi-día; CoccBCS/Nayarit) |
| `hora_salida`, `hora_llegada` | TEXT | ✓ | Horas (texto libre; CoccBCS/Nayarit) |
| `formulario_id` | UUID → formulario | ✓ | Versión del formulario con que se capturó (0002; NULL en legacy) |
| `formulario_version` | NUMERIC(4,2) | ✓ | Versión estampada (0016: decimal, p. ej. 0.8) |
| `created_at`, `updated_at` | TIMESTAMPTZ | ✗ | Auditoría (trigger `touch_updated_at`) |
| `created_by` | TEXT | ✓ | Quién creó el registro |
| `synced_at` | TIMESTAMPTZ | ✓ | Momento de sincronización desde la tablet |
| `device_id` | TEXT | ✓ | Dispositivo de origen |

**Índices relevantes:** por fecha, comunidad, zona, embarcación, técnico, formato, sitio,
región y legacy_id. **Unicidad natural** para registros nuevos:
`(fecha, embarcacion_id, comunidad_id, tipo_registro)` cuando `legacy_id IS NULL`.

---

## 4. Tablas hijas de la faena (todas con `ON DELETE CASCADE`)

### `faena_especie_objetivo` — especie(s) que se buscaban
| Columna | Tipo | Descripción |
|---|---|---|
| `faena_id` | UUID → faena | |
| `especie_id` | UUID → cat_especie | UNIQUE(faena, especie) |
| `es_historico` | BOOLEAN | TRUE = migrado (puede haber N); FALSE = nuevo (máx. 1 por faena, forzado por trigger) |

### `faena_arte` — arte(s) de pesca empleados (N por faena)
| Columna | Tipo | Descripción |
|---|---|---|
| `tipo_arte_id` | UUID → cat_tipo_arte (NOT NULL) | Arte |
| `metodo` | TEXT | Para Piola: Línea / Palangar / Rendal |
| `caida_m`, `longitud_m`, `luz_malla_pulg` | NUMERIC ≥ 0 | Dimensiones de red |
| `material`, `calibre_piola` | TEXT | Calibre acepta compuestos ("60 y 45") |
| `tipo_anzuelo_id` | UUID → cat_tipo_anzuelo | |
| `numero_anzuelo` | INT > 0 | Número comercial (4, 8, 10…) |
| `ancho_anzuelo`, `largo_anzuelo` | NUMERIC > 0 | En mm |
| `anzuelos_trabajando`, `num_artes`, `num_lances` | INT | Esfuerzo |
| `tiempo_remojo_h`, `ancho_boca_pulg` | NUMERIC | Trampas/redes |
| `tipo_operacion_id` | UUID → cat_tipo_operacion | Fondo / media agua / aboyado |
| `observaciones` | TEXT | |

### `captura` — captura por especie
| Columna | Tipo | Descripción |
|---|---|---|
| `especie_id` | UUID → cat_especie (NOT NULL) | |
| `categoria_tamano` | TEXT | Ej. I, II (Huachinango I/II) |
| `presentacion` | TEXT | Entero, Eviscerado, Filete, Cola… |
| `captura_kg` | NUMERIC(10,3) ≥ 0 (NOT NULL) | Kilogramos desembarcados |
| `num_organismos` | INT ≥ 0 | |
| `precio_kg` | NUMERIC(10,2) ≥ 0 | Precio de playa |
| `tipo_captura` | TEXT ∈ {OBJETIVO, ACOMPANAMIENTO} | Buscada vs incidental |
| `observaciones` | TEXT | |

### `medicion` — medición biológica individual (~377K registros históricos)
| Columna | Tipo | Descripción |
|---|---|---|
| `faena_id` | UUID → faena (NULL permitido) | NULL = medición huérfana pre-2013 |
| `captura_id` | UUID → captura (SET NULL) | Captura asociada |
| `especie_id` | UUID → cat_especie (NOT NULL) | |
| `longitud_total_cm` | NUMERIC(7,2) > 0 (NOT NULL) | **Siempre en cm** (históricos en mm se dividieron ÷10) |
| `longitud_furcal_cm` | NUMERIC(7,2) > 0 | Opcional (CM-05, Boca del Álamo) |
| `longitud_sospechosa` | BOOLEAN DEFAULT FALSE | (0009) marcada si excede `cat_especie.longitud_maxima_cm` |
| `peso_gr` | NUMERIC(10,2) > 0 | **Siempre en gramos** (la app captura kg y multiplica ×1000) |
| `procesado` | procesado_enum | ENTERO / EVISCERADO (interpreta el peso) |
| `sexo` | sexo_enum | |
| `peso_gonada_gr` | NUMERIC(8,2) ≥ 0 | |
| `madurez_nikolsky` | madurez_nikolsky_enum | NA, 1–6 |
| `tipo_anzuelo_id`, `numero_anzuelo`, `ancho_anzuelo`, `largo_anzuelo` | — | Anzuelo con que se capturó (mm) |
| `observaciones` | TEXT | |

### `carnada` — carnada usada (N por faena)
`especie_id → cat_especie` o `nombre_libre TEXT` (CHECK: al menos uno) ·
`origen origen_carnada_enum` · `sitio_pesca_carnada_id → cat_sitio_pesca` o `sitio_libre`
· `kg_aprox NUMERIC(8,2) > 0 (NOT NULL)` · `arte_pesca_id → cat_tipo_arte`.

### `interaccion_etp` — interacciones con especies protegidas (N por faena)
`especie_id → cat_especie` · `tipo_interaccion_id → cat_tipo_interaccion_etp` ·
`cantidad INT ≥ 1` · `observaciones`.

### `gasto` — gastos del viaje (N por faena)
`tipo_gasto_id → cat_tipo_gasto` · `cantidad`, `precio_unitario NUMERIC ≥ 0` ·
`monto_total NUMERIC(12,2) ≥ 0 (NOT NULL)` · `descripcion` (concepto cuando tipo = Otro).

### `recurso_ahorro` / `aportacion_imss` — exclusivas del formato Nota de Pago
`recurso_ahorro`: parte de la captura destinada a ahorro (`especie_id`, `descripcion`,
`kilos`, `monto_ahorro NOT NULL`). `aportacion_imss`: una por faena (`faena_id UNIQUE`,
`monto NOT NULL`).

---

## 5. Formularios dinámicos

### `formulario` (0002) — definición versionada del formulario de captura
| Columna | Tipo | Descripción |
|---|---|---|
| `nombre` | TEXT | Nombre del formulario |
| `formato_origen_id` | UUID → cat_formato_origen | Ámbito (formato/región); UNIQUE(formato, version) |
| `version` | NUMERIC(4,2) | **Decimal, asignada por el admin** (0016; antes INT) |
| `estado` | estado_formulario_enum | borrador → publicado → archivado |
| `definicion` | JSONB (NOT NULL) | Secciones → campos: binding (core/custom/ui), `visible_si`, repetible+entidad, opciones priorizadas, unidad de captura… |
| `constantes` | JSONB | Valores fijos del formulario (región/zona/tipo_registro) |
| `created_by`, `created_at`, `published_at` | — | Auditoría |

**Regla clave (trigger `formulario_inmutable_publicado`):** una versión publicada es
**inmutable** — no puede cambiarse su `definicion`/`constantes`; se crea la versión
siguiente. Así cada faena sabe exactamente con qué formulario se capturó.

### `campo_formulario` — registro de campos personalizados (EAV)
`codigo TEXT UNIQUE` · `etiqueta` · `tipo_dato tipo_dato_campo_enum` · `opciones_json
JSONB` (para SELECT) · `formato_origen_id` · `formulario_id → formulario` (0002; versión
dueña del campo custom) · `activo` · `orden`.

### `valor_campo_faena` — valores de campos personalizados por faena (EAV)
`faena_id → faena (CASCADE)` · `campo_formulario_id → campo_formulario` · `valor TEXT` ·
UNIQUE(faena, campo).

### `lista_opcion` (0013) — listas curadas de opciones por formulario
| Columna | Tipo | Descripción |
|---|---|---|
| `formato_origen_id` | UUID → cat_formato_origen (CASCADE) | Formulario dueño |
| `lista` | TEXT | 'especies' \| 'carnada' \| 'pescadores' \| … |
| `tabla` | TEXT | Catálogo referenciado (polimórfico: cat_especie, cat_pescador…) |
| `registro_id` | UUID | Fila del catálogo (integridad garantizada por la herramienta de importación y por `merge_catalog_by_name`) |
| `importancia` | INT DEFAULT 0 | Mayor = más arriba en el selector |

UNIQUE(formato, lista, registro). La tablet toma las opciones de cada campo de lista de
aquí (subconjunto estricto y ordenado), no del catálogo completo.

---

## 6. Usuarios, gobernanza y consola

### `usuario` (0004, 0012, 0015) — perfil de usuario
| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID PK | **= `auth.users.id` de Supabase Auth** (la contraseña vive en Auth, no aquí) |
| `nombre` | TEXT | |
| `email` | TEXT UNIQUE | |
| `rol` | rol_usuario_enum | TECNICO / ADMINISTRADOR / ANALISTA (alimenta RLS) |
| `region_id` | UUID → cat_region | Ámbito para RLS/candado de región (NULL = todas) |
| `activo` | BOOLEAN | Desactivación de cuenta |
| `tecnico_id` | UUID → cat_tecnico (0012) | Vínculo del login con su técnico de catálogo |
| `pescador_id` | UUID → cat_pescador (0012) | Vínculo opcional con pescador |
| `created_by` | UUID (0012) | Admin que creó la cuenta |
| `formato_origen_id` | UUID → cat_formato_origen (0015) | **Formulario asignado** al técnico (la tablet bloquea si es NULL) |

### `catalogo_config` (0003) — configuración por catálogo
`tabla TEXT PK` · `permite_propuestas BOOLEAN` — ¿la app ofrece "Otro/proponer"? (UX;
el control duro es el rol vía RLS). Activado para: cat_pescador, cat_embarcacion,
cat_sitio_pesca, cat_especie.

### `tecnico_comunidad` (0003) — técnicos por comunidad (N:M)
`(tecnico_id, comunidad_id)` PK compuesta. Alimenta la cascada Comunidad→Técnico del
formulario (si está vacía, se muestran todos los técnicos).

### `cambio_catalogo` (0003) — bitácora de cambios de catálogos
`tabla` · `registro_id` · `accion` (crear/editar/aprobar/fusionar/rechazar/separar) ·
`detalle JSONB` ({campo, antes, después} o {survivor}) · `usuario_id` · `created_at`.

### `consulta_export` (0014) — consultas de descarga guardadas
`usuario_id → usuario (CASCADE)` · `nombre` (UNIQUE por usuario) · `config JSONB`
(especificación re-ejecutable, no SQL congelado) · `compartida BOOLEAN` (visible a otros
usuarios de consola) · timestamps. Con RLS: cada quien ve las suyas + las compartidas.

### `_migrations` — control de esquema
Registro interno de `scripts/apply.py`: qué migraciones ya se aplicaron (16 al corte).

---

## 7. Funciones y triggers

| Objeto | Tipo | Propósito |
|---|---|---|
| `crear_faena_completa(payload jsonb)` | RPC (0005, ampliada en 0008/0011) | **Punto de entrada de la app.** Inserta atómicamente el grafo completo de una faena (faena + especie objetivo + artes + capturas + mediciones + carnada + ETP + gastos + campos custom) en una transacción. **Idempotente** por UUIDs de cliente: reenviar la misma faena no duplica. También registra propuestas de catálogo del payload. |
| `merge_catalog_by_name(...)` | Función (0010, ampliada en 0013) | Fusión de entradas duplicadas de catálogo: repunta por descubrimiento de FKs todas las referencias (incluida la polimórfica `lista_opcion`) hacia la entrada sobreviviente. |
| `touch_updated_at()` + `trg_faena_updated` | Trigger | Mantiene `faena.updated_at` |
| `formulario_inmutable_publicado()` | Trigger (0002) | Impide editar la definición de un formulario publicado |
| `trg_especie_objetivo_unica` | Trigger | Máximo 1 especie objetivo no-histórica por faena |
| `_prep(...)` | Función auxiliar (0005) | Normaliza arreglos JSON del payload de la RPC |

---

## 8. Seguridad a nivel de fila (RLS)

Activada por la migración **0007** (y ampliada en 0013/0014): 32 políticas en producción.
Postura general:

- **Rol anónimo:** bloqueado (verificado).
- **`authenticated` (técnicos):** lectura de catálogos aprobados, formulario publicado y
  listas curadas; escritura únicamente vía la RPC `crear_faena_completa`; propuestas de
  catálogo según `catalogo_config`.
- **Consola:** opera con el DSN directo/service-role (omite RLS) protegida por su propia
  puerta de login por rol; el candado de región del ANALISTA se aplica en la capa de
  aplicación de exportaciones.
- `consulta_export`: RLS por dueño + compartidas.
