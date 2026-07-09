# Cuestionario de Transferencia Técnica

Respuestas elaboradas con base en el contenido real de los repositorios en esta carpeta
(`capture-app`, `catalog-review-app`, `supabase-backend`, `report-automation`) al 2026-07-09.

---

## 1. Arquitectura del sistema

**1.1 ¿Cómo está compuesto el sistema?**

El sistema consta de cuatro componentes, cada uno en su propio repositorio:

1. **`capture-app` — Aplicación móvil de captura en campo.** App *offline-first*
   construida con Expo / React Native, que es **multiplataforma: el mismo código corre
   en Android y en iOS**. El despliegue actual es un APK para tablets Android/Huawei
   (sin servicios de Google), pero generar la versión iOS solo requiere una compilación
   adicional con EAS (`eas build --platform ios`) y una cuenta de Apple Developer — sin
   cambios de código. Renderiza dinámicamente el formulario publicado por el
   administrador, captura faenas de pesca sin conexión (faena → captura → medición) y
   las sincroniza de forma atómica e idempotente a la base de datos cuando hay red.
   *Nota:* el mapa interactivo con pin (MapLibre) y la ubicación GPS (expo-location)
   **no están implementados en la versión actual**; están planteados para versiones
   futuras.
2. **`catalog-review-app` — Consola de administración (dashboard web).** Herramienta para
   administradores: gestión de catálogos y duplicados, revisión de propuestas de los
   técnicos, constructor de formularios versionados, listas curadas (especies, carnada,
   pescadores), gestión de usuarios y roles, exportación/descarga de datos (con
   constructor de consultas), y limpieza de datos de prueba.
3. **`supabase-backend` — Base de datos y lógica de servidor.** PostgreSQL alojado en
   Supabase, definido íntegramente como migraciones SQL ordenadas (0001–0015):
   esquema, definición de formularios versionados, gobernanza de catálogos, usuarios y
   roles, políticas de seguridad a nivel de fila (RLS), y la RPC `crear_faena_completa`
   (inserción atómica e idempotente del grafo completo de una faena). No hay API
   intermedia propia: se usan los servicios nativos de Supabase (PostgREST + Auth).
4. **`report-automation` — Servicio de reportes de radar M2 (independiente).** Servicio
   Python autónomo que, con calendario mensual, consulta la API de ProtectedSeas M2
   para los 6 sitios de radar configurados (Loreto, Loreto 2, San Basilio, Islas Marías,
   El Pardito, Espíritu Santo), genera un PDF por sitio con el formato del "Reporte de
   Actividad del M2" y lo envía por correo a la lista de destinatarios de cada sitio.
   Incluye un panel de administración web propio. **No depende de Supabase**: usa su
   propia base SQLite.

**1.2 ¿Qué tecnologías utilizaron para cada componente?**

| Componente | Tecnologías |
|---|---|
| App de captura | Expo / React Native, TypeScript (multiplataforma Android + iOS); SQLite local (outbox offline); cliente Supabase JS. Compilación con EAS (hoy APK Android; iOS disponible con build adicional). *Planeado a futuro:* MapLibre + OpenStreetMap (mapa con pin, sin Google) y expo-location (GPS). |
| Consola admin | Python, Streamlit, pandas, psycopg2 (conexión directa a Postgres), pyarrow; empaquetada con Docker + Docker Compose y Caddy (HTTPS automático con Let's Encrypt). |
| Backend | PostgreSQL (Supabase), SQL puro en migraciones versionadas, PostgREST (API REST automática), Supabase Auth (GoTrue), RLS; scripts de operación en Python (psycopg2). |
| Reportes M2 | Python 3.12, Flask + HTMX (panel admin), APScheduler (cron mensual), httpx (API), pandas, matplotlib (gráficas), Jinja2 + WeasyPrint (PDF), smtplib (correo), SQLite + SQLAlchemy, Docker. |

**1.3 ¿Cómo se comunican entre sí?**

- **App → Base de datos:** por HTTPS contra la API de Supabase. La app se autentica con
  Supabase Auth (correo + contraseña), descarga el formulario publicado y los catálogos
  aprobados vía PostgREST, y sube faenas llamando a la RPC `crear_faena_completa`. Los
  IDs son UUID generados en el cliente y la RPC es idempotente, por lo que reintentar
  tras un corte de red nunca duplica datos.
- **Consola → Base de datos:** conexión directa a PostgreSQL (psycopg2, `DATABASE_URL`)
  para catálogos/formularios/exportaciones, y la API de administración de Supabase Auth
  (con la service-role key, solo del lado servidor) para crear cuentas de usuario.
- **Servicio de reportes:** es independiente; se comunica con la API externa de
  ProtectedSeas M2 y con un servidor SMTP. No toca la base de Supabase.

---

## 2. Código fuente y documentación

**2.1 ¿Se entregará el código fuente completo?**
Sí. Los cuatro componentes son código fuente completo, sin partes compiladas u ocultas.

**2.2 ¿Se entregará el repositorio Git con su historial?**
Sí. Los cuatro repositorios ya están en GitHub bajo la organización **PronaturaNoroeste**
(`capture-app`, `catalog-review-app`, `supabase-backend`, `report-automation`), con su
historial de cambios completo.

**2.3 ¿Qué documentación técnica se entregará?**

Documentación que ya existe en los repositorios:

- **Instalación / despliegue:** `catalog-review-app/DEPLOY.md` (consola en VPS con
  Docker), `capture-app/BUILD.md` (compilar el APK con EAS),
  `supabase-backend/PROD_ROLLOUT.md` (runbook completo de puesta en producción),
  `supabase-backend/README.md` (levantar un proyecto nuevo desde cero: crear proyecto →
  correr migraciones → copiar catálogos).
- **Arquitectura:** README de cada repo con diagramas de flujo;
  `report-automation/m2_report_automation_architecture.md` (arquitectura completa del
  servicio de reportes); `handoff.md` (estado, cuentas, secretos, gotchas).
- **Base de datos:** las 15 migraciones SQL comentadas son la definición autoritativa
  del esquema.
- **Pruebas en dispositivo:** `capture-app/DEVICE_TESTING.md`.

**Documentos de entrega generados** (en la raíz de esta carpeta, junto a este archivo):
`Manual_de_Usuario.md` (técnicos, administradores y analistas),
`Diccionario_de_Datos.md` (diccionario formal de la base de datos) y
`Diagrama_Arquitectura.md` (diagramas UML en Mermaid: componentes, despliegue,
secuencia de sincronización y modelo entidad–relación). Ver sección 9.

---

## 3. Configuración del sistema

**3.1 ¿Dónde se configura la conexión a la base de datos y demás servicios?**
En archivos `.env` (uno por repositorio), y cada repo incluye un **`.env.example`**
documentado que indica exactamente qué variables se necesitan:

- `capture-app/.env` → `EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_ANON_KEY`
  (para builds de producción se definen como variables de entorno de EAS).
- `catalog-review-app/.env` → `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
  `SUPABASE_SERVICE_ROLE_KEY`.
- `supabase-backend/.env` → `DATABASE_URL` (dev) y `PROD_DATABASE_URL`.
- `report-automation` → `.env` con credenciales SMTP y token de la API M2.

**3.2 ¿La configuración está en archivos/variables de entorno o en el código?**
En variables de entorno. Los `.env` están en `.gitignore` (nunca se versionan), el código
lee primero del entorno del sistema y después del archivo, y el Dockerfile de la consola
no copia el `.env` a la imagen. No hay credenciales escritas en el código fuente.

**3.3 Si cambiamos de servidor o de base de datos, ¿qué tan complejo sería migrar?**

- **La consola y el servicio de reportes:** triviales de mover — son contenedores Docker;
  se copian al nuevo servidor, se pone el `.env` y `docker compose up`.
- **La base de datos:** es PostgreSQL estándar y todo el esquema es reproducible por
  migraciones (`scripts/apply.py`), así que moverse **a otro proyecto de Supabase** es
  sencillo y está documentado, y moverse **a un servidor propio** es viable
  auto-hospedando Supabase (software libre) sin cambios de código. El procedimiento
  detallado de las tres rutas de migración está en la respuesta **6.1**.

---

## 4. Seguridad

**4.1 ¿Cómo se almacenan las contraseñas?**
Se utiliza **Supabase Auth** (correo + contraseña, cuentas creadas por un administrador
desde la consola). Las contraseñas las gestiona y cifra Supabase (hash bcrypt en su
esquema interno de auth); nunca se guardan en tablas propias ni en texto plano.

**4.2 ¿Las credenciales del sistema están protegidas o dentro del código?**
Protegidas: viven solo en `.env` (gitignored) o variables de entorno del servidor/EAS.
La **service-role key** (que omite RLS) existe únicamente en el servidor de la consola —
nunca en la app, en git, en la imagen Docker ni en logs. La **anon key** que va dentro
del APK es la llave *publicable* de Supabase, diseñada para ser pública: por sí sola solo
permite lo que las políticas RLS autoricen.

**4.3 ¿Hay roles y permisos?**
Sí, tres roles: **ADMINISTRADOR**, **ANALISTA** y **TECNICO**, guardados en la tabla
`usuario` (con región asignada). Se aplican en dos capas: (a) **RLS en la base de datos**
(migración `0007_auth_rls.sql` y posteriores; 32 políticas activas en producción, con
acceso anónimo bloqueado — verificado con prueba autenticada), y (b) la **puerta de
login de la consola**, que solo admite roles de consola. Además cada técnico tiene un
formato/formulario asignado y la tablet bloquea si no lo tiene; el rol ANALISTA queda
restringido a los datos de su propia región en las exportaciones (candado de región,
R-C) y sin acceso al constructor de consultas.

**4.4 ¿Se registran bitácoras (logs)?**
Parcialmente:

- Supabase registra logs de autenticación y de API (visibles en su dashboard).
- La migración `0003` añade un **registro de cambios de catálogos** (quién propuso/aprobó).
- La consola y los contenedores emiten logs de aplicación (`docker compose logs`).

No existe todavía una bitácora de auditoría unificada de todas las acciones de usuario;
si la organización la requiere, debe acordarse como mejora.

**4.5 ¿Qué medidas hay contra inyección SQL, XSS y acceso no autorizado?**

- **Inyección SQL:** todas las consultas de la consola usan parámetros de psycopg2
  (nunca concatenación de valores del usuario); la app no ejecuta SQL — llama RPCs con
  payload JSON tipado.
- **Acceso no autorizado:** RLS por rol/región en cada tabla; el rol anónimo está
  bloqueado; la service-role key nunca sale del servidor.
- **XSS:** la consola es Streamlit (escapa el contenido por defecto, sin HTML crudo de
  usuario); todo el tráfico va sobre HTTPS (Caddy con certificados Let's Encrypt).

**4.6 ¿Se hicieron pruebas de seguridad o revisiones antes de producción?**
Se hicieron: prueba de humo de RLS en producción con usuario autenticado (técnico lee
catálogos/formulario/listas; anónimo bloqueado), pruebas unitarias de la lógica de la
app, pruebas de la consola contra base de desarrollo, y verificación end-to-end del flujo
completo (captura offline → sync → datos correctos en la BD, con los 377,179 registros
históricos intactos tras la migración). **No** se ha realizado un pentest formal por un
tercero; si se requiere, debe contratarse por separado.

---

## 5. Mantenimiento y evolución

**5.1 ¿Un desarrollador con experiencia podrá mantenerlo solo con la documentación?**
Sí, con el perfil adecuado: experiencia en **Python/SQL** (consola y backend) y en
**React Native/TypeScript** (app). Los puntos que más lo facilitan: el esquema completo
es reproducible con un comando (`apply.py`), cada repo tiene README + runbook de
despliegue, hay `.env.example` en todos, y `handoff.md` documenta el estado, las cuentas
y los errores ya resueltos ("gotchas") para no repetirlos.

**5.2 ¿Qué partes son más complejas de mantener?**

- El **motor del formulario dinámico** en la app (`src/forms/`: visibilidad condicional,
  validaciones, mapeo de respuestas al payload de la RPC, conversión kg→gr).
- La **RPC `crear_faena_completa`** (inserción atómica del grafo faena/captura/medición).
- El **constructor de exportaciones** de la consola (descubrimiento de relaciones por
  llaves foráneas).
- El **proceso de build del APK** (EAS; las variables `EXPO_PUBLIC_*` se incrustan en
  tiempo de compilación — documentado en `BUILD.md`).

**5.3 ¿El sistema fue diseñado para crecer (nuevas encuestas, reportes, funciones)?**
Sí, ese fue un objetivo central de diseño:

- **Nuevas encuestas/formularios no requieren programar:** el administrador los crea en
  el constructor de formularios de la consola, se publican como versiones inmutables y
  la app los renderiza dinámicamente. Cada técnico puede tener asignado un formato
  distinto.
- **Nuevos reportes/exportaciones:** el constructor de consultas permite armar y guardar
  exportaciones personalizadas sin tocar código.
- **Cambios de esquema:** se agregan como nuevas migraciones ordenadas (nunca se edita
  una aplicada), lo que mantiene reproducible cualquier entorno.
- **Nuevos sitios de radar** (reportes M2): se dan de alta desde el panel admin, no en código.

---

## 6. Base de datos e infraestructura

**6.1 ¿Es indispensable Supabase o puede migrarse a un servidor propio?**
No es indispensable, pero hoy provee tres cosas: PostgreSQL, la autenticación y la API
REST. La base es Postgres estándar y 100% reproducible por migraciones. Hay tres rutas
de salida, de menor a mayor esfuerzo:

**Ruta 1 — Otro proyecto de Supabase** (p. ej. cambiar de organización/cuenta o de plan).
Esfuerzo: horas. El procedimiento ya existe y se ejerció al montar producción:

1. Respaldar el proyecto actual: `pg_dump -Fc` del esquema `public` (rollback garantizado).
2. Crear el proyecto nuevo y aplicar el esquema: `python scripts/apply.py` con el
   `DATABASE_URL` del proyecto nuevo (aplica las 16 migraciones en orden; idempotente,
   lleva registro en la tabla `_migrations`).
3. Restaurar los datos con `pg_restore` (o, si solo se necesitan catálogos y formularios,
   `scripts/copy_catalogs.py` + `seed_form.py`).
4. Recrear las cuentas de usuario en Auth del proyecto nuevo (desde la consola, 👤
   Usuarios) — los usuarios de Auth no viajan en el `pg_dump` del esquema `public`.
5. Repuntar los clientes: cambiar `SUPABASE_URL`/llaves y `DATABASE_URL` en el `.env` de
   la consola (`docker compose up -d` para recargar) y las variables `EXPO_PUBLIC_*` en
   EAS + recompilar el APK (son constantes de tiempo de compilación).

**Ruta 2 — Supabase auto-hospedado en un servidor de la organización.** Esfuerzo: días.
Supabase es software libre y se distribuye como un stack de Docker Compose (Postgres +
GoTrue/Auth + PostgREST + Kong). Se instala en un VPS propio, y a partir de ahí el
procedimiento es idéntico a la Ruta 1 (aplicar migraciones → restaurar datos → recrear
usuarios → repuntar URLs y llaves). **No requiere ningún cambio de código** en la app ni
en la consola, porque ambas hablan los mismos protocolos (PostgREST y GoTrue). Lo que sí
asume la organización: administrar ese servidor (actualizaciones, respaldos, TLS,
monitoreo). Es la ruta recomendada si el requisito es "todo en infraestructura propia".

**Ruta 3 — Postgres "puro" sin Supabase.** Esfuerzo: semanas de desarrollo. Los datos y
el esquema migran igual (pg_dump/pg_restore — es Postgres estándar), y la consola casi no
cambia (usa conexión directa `DATABASE_URL`), pero habría que **desarrollar reemplazos**
para lo que Supabase provee a la app: un servicio de autenticación (emisión y validación
de JWT, reset de contraseña) y una API HTTP que exponga los endpoints que la app consume
(descarga de formulario/catálogos/listas y la llamada a la RPC `crear_faena_completa`),
además de reescribir el cliente de la app. Solo tiene sentido si existe una prohibición
de usar el stack de Supabase incluso auto-hospedado.

En los tres casos la lógica de negocio no se toca: vive en SQL (migraciones + RPCs) y en
los clientes, no en servicios propietarios de Supabase.

**6.2 ¿Qué infraestructura se necesita para operar?**

- **Proyecto Supabase** (actualmente capa gratuita; la BD ocupa ~226 MB de los 500 MB
  del límite gratuito — hay que vigilarlo y pasar a plan Pro si se acerca al tope).
- **Un VPS con Docker** para la consola, con un dominio/registro DNS (Caddy gestiona el
  certificado HTTPS solo). El mismo VPS puede hospedar el servicio de reportes M2.
- **Cuenta de Expo (gratuita)** para compilar nuevos APK con EAS.
- **Tablets Android/Huawei** para captura (la app se instala por APK, sin Play Store).
  Por ser Expo/React Native la app también puede compilarse **para iOS** (requiere
  cuenta de Apple Developer y `eas build --platform ios`).
- Para reportes M2: token de la API de ProtectedSeas y un servidor/relay SMTP.

**6.3 ¿Existen respaldos automáticos?**
**Hoy no hay respaldos automáticos**: la capa gratuita de Supabase no incluye backups de
dashboard. Existe un respaldo manual verificado (`pg_dump -Fc` del esquema `public`,
33 MB, previo a la migración de producción del 2026-07-07) que sirve como punto de
restauración con `pg_restore`. Los **respaldos automáticos y bajo demanda están en el
backlog (punto R6)** y deben implementarse (o cubrirse pasando al plan Pro de Supabase,
que incluye backups diarios) **antes de dar el sistema por transferido**. Procedimiento
de restauración: `pg_restore` contra el proyecto, documentable en el runbook.

---

## 7. Calidad del desarrollo

**7.1 ¿Se usaron herramientas de IA? ¿El código fue revisado y probado?**
Sí, el desarrollo se realizó con asistencia de herramientas de IA (Claude Code) bajo
dirección y revisión del equipo. Todo el código entregado fue revisado, comprendido y
probado: hay pruebas unitarias de la lógica de la app (mapeo de payload, motor de
visibilidad/validación, cola offline), pruebas de la consola contra base de desarrollo,
y verificación end-to-end del flujo real contra la base de datos (incluida la
idempotencia de la sincronización y la migración de producción verificada con los datos
históricos intactos).

**7.2 ¿Limitaciones, errores conocidos o pendientes?**
Sí, están documentados en `handoff.md` y `TODO.md`:

- **Respaldos automáticos (R6) — el pendiente más importante** (ver 6.3).
- El backlog de mejoras **R-A a R-F ya fue implementado y entregado**: mensajes de login
  claros (R-A), mostrar solo formatos vigentes (R-B), candado de región para el rol
  ANALISTA (R-C), filtros por valor en el constructor de exportaciones (R-D),
  restablecimiento de contraseña de autoservicio por código enviado al correo — consola
  y tablet (R-E), y versiones decimales de formulario ingresadas por el administrador
  (R-F, con la migración 0016 ya aplicada a producción).
- **Mapa con pin (MapLibre) y GPS (expo-location) en la app**: no implementados;
  planteados para versiones futuras.
- Importación masiva desde Excel (R5) planeada, no construida.
- Límite de 500 MB de la capa gratuita de Supabase (uso actual ~226 MB).
- No hay pentest de terceros ni bitácora de auditoría unificada (ver 4.4, 4.6).

---

## 8. Propiedad intelectual

**8.1 / 8.2** Esto se define por acuerdo escrito, no por el código; se recomienda dejarlo
explícito en el convenio de servicio social / carta de entrega. En la práctica el control
ya está del lado de la organización: los cuatro repositorios viven en la organización de
GitHub **PronaturaNoroeste** (no en cuentas personales), y las cuentas de Supabase, Expo,
VPS y dominio deben quedar a nombre de la organización. La intención de la entrega es que
Pronatura Noroeste tenga derecho pleno a usar, modificar, ampliar y mantener el sistema
sin restricción ni dependencia de los desarrolladores originales o de la universidad —
solo falta formalizarlo por escrito.

---

## 9. Entrega del proyecto

| Entregable | Estado |
|---|---|
| Código fuente completo | ✅ Ya en GitHub (4 repos, org PronaturaNoroeste) |
| Base de datos y scripts de creación | ✅ 15 migraciones SQL + scripts (`apply.py`, seeds, copia de catálogos) |
| Manual de instalación | ✅ `DEPLOY.md`, `BUILD.md`, `PROD_ROLLOUT.md`, READMEs |
| Manual técnico | ✅ READMEs + docs de arquitectura + `handoff.md` + `Diccionario_de_Datos.md` + `Diagrama_Arquitectura.md` |
| Manual para desarrolladores | 🔶 Parcial (mismo material); falta guía de "cómo agregar X" |
| Manual de usuario | ✅ `Manual_de_Usuario.md` (técnicos de campo, administradores y analistas) |
| Diagrama de arquitectura | ✅ `Diagrama_Arquitectura.md` (UML en Mermaid: componentes, despliegue, secuencia, E-R) |
| Modelo / diccionario de la base de datos | ✅ `Diccionario_de_Datos.md` (diccionario formal generado desde las migraciones) |
| Archivo de configuración de ejemplo | ✅ `.env.example` en todos los repos |
| Documentación de despliegue en nuevo servidor | ✅ `DEPLOY.md` (Docker/VPS) + `PROD_ROLLOUT.md` + README backend |
| Capacitación / transferencia de conocimiento | ⏳ Por agendar (sesiones admin de consola + build de APK + operación de BD) |

---

## Pregunta final

**¿Podrá otro desarrollador continuar en dos años solo con lo entregado? ¿Qué evidencia
lo garantiza?**

Sí, y la garantía no es una promesa sino propiedades verificables del entregable:

1. **Reproducibilidad total del backend:** cualquier persona puede levantar un entorno
   idéntico con tres pasos documentados (crear proyecto Postgres → `python scripts/apply.py`
   → copiar catálogos). Esto ya se ejerció en la práctica: producción se montó sobre la
   base histórica siguiendo exactamente ese runbook, con verificación posterior.
2. **Despliegues de un comando:** la consola y el servicio de reportes son
   `docker compose up` con un `.env`; no dependen de la máquina de nadie.
3. **Sin conocimiento oculto:** no hay credenciales ni configuración en el código; cada
   repo trae `.env.example` que enumera todo lo que hay que proveer; `handoff.md`
   documenta cuentas, proyectos, respaldos y hasta los errores ya cometidos y su solución.
4. **Historial Git completo** en la organización de GitHub de Pronatura, con los commits
   que explican cada cambio.
5. **Diseño que reduce la necesidad de programar:** nuevas encuestas, listas, usuarios y
   exportaciones se hacen desde la consola, sin desarrollador.
6. **Pruebas automatizadas** de la lógica crítica de la app, que un nuevo desarrollador
   puede correr (`npm test`) para verificar que no rompió nada.
