# Manual de Usuario — Sistema de Bitácoras Pesqueras Pronatura Noroeste

Este manual cubre los tres perfiles de usuario del sistema:

| Perfil | Herramienta que usa | Qué puede hacer |
|---|---|---|
| **Técnico de campo (TECNICO)** | App de captura en tablet | Capturar faenas de pesca sin conexión y sincronizarlas |
| **Administrador (ADMINISTRADOR)** | Consola web de administración | Gobernar catálogos, formularios, listas, usuarios y datos |
| **Analista (ANALISTA)** | Consola web de administración | Descargar/exportar los datos de su región |

Todas las cuentas se crean con **correo y contraseña** por un administrador desde la
consola (👤 Usuarios). No existe auto-registro.

---

# Parte 1 — App de captura (técnicos de campo)

## 1.1 Qué es

La app de captura permite registrar una **faena de pesca completa** (datos del viaje,
artes de pesca, capturas por especie, mediciones biológicas, carnada, gastos e
interacciones con especies protegidas) directamente en la tablet, **sin necesidad de
internet**. Cuando la tablet vuelve a tener conexión, las faenas guardadas se envían a la
base de datos central con un toque.

La app funciona en Android (instalación actual, por archivo APK — no requiere Play Store
ni servicios de Google) y puede compilarse también para iOS.

> **Nota de versión:** el mapa interactivo con pin de ubicación y la captura automática
> de GPS están planeados para una versión futura; en la versión actual la ubicación se
> registra seleccionando el sitio de pesca del catálogo.

## 1.2 Instalación (Android)

1. Recibirás el archivo **APK** (o un enlace de descarga) del administrador.
2. En la tablet, abre el archivo y acepta "instalar aplicaciones de origen desconocido"
   si el sistema lo pide (es normal en instalaciones fuera de la tienda).
3. Al terminar aparecerá el ícono de la app en la pantalla de inicio.

## 1.3 Iniciar sesión

1. Abre la app. Necesitas **internet solo para iniciar sesión la primera vez**.
2. Escribe el **correo** y la **contraseña** que te entregó el administrador.
3. Al entrar, la app descarga automáticamente:
   - el **formulario asignado a tu usuario** (p. ej. "Boca del Álamo", con su versión
     visible en la barra superior, p. ej. `v0.8`), y
   - los **catálogos y listas** (especies, carnada, pescadores, embarcaciones, sitios…).
4. Si ves un mensaje de bloqueo indicando que no tienes formulario asignado, contacta al
   administrador para que te asigne uno (Parte 2, sección 2.7).

**¿Olvidaste tu contraseña?** En la pantalla de inicio de sesión usa la opción de
restablecer contraseña: escribe tu correo, recibirás un **código** por email, ingrésalo
en la app y define tu nueva contraseña. (También disponible en la consola web.)

## 1.4 Capturar una faena (sin internet)

1. Toca **Nueva faena**. El formulario se muestra por secciones (datos generales, arte de
   pesca, capturas, mediciones, carnada, gastos, etc.).
2. Llena los campos. Ten en cuenta:
   - Los campos con lista (especie, sitio, pescador…) se eligen con un **buscador**:
     escribe unas letras y toca la opción. Las opciones más usadas aparecen primero.
   - Algunas secciones o campos **aparecen o desaparecen según lo que respondas** (p. ej.
     los campos de anzuelo solo aparecen si el arte lo lleva; la sección de carnada se
     omite si no usaste carnada). Es el comportamiento esperado.
   - Los **pesos se capturan en kilogramos**; el sistema los guarda internamente en la
     unidad correcta, no tienes que convertir nada.
   - Si un valor está fuera de rango o falta un campo obligatorio, la app lo marca y no
     deja guardar hasta corregirlo.
   - Si una opción no existe en la lista (una especie nueva, un pescador nuevo, una
     embarcación o sitio nuevos), usa la opción **"Otro / proponer"**: tu propuesta se
     envía a revisión del administrador; mientras tanto tu faena se guarda con ella.
3. Al terminar, guarda. Verás **"✓ Faena guardada en el dispositivo"** y el contador de
   faenas **sin sincronizar**. La faena está segura en la tablet aunque se apague o no
   haya señal.
4. Toca **Nueva faena** para capturar la siguiente.

## 1.5 Sincronizar

1. Cuando tengas internet (WiFi o datos), toca el botón **Sincronizar (N)** de la barra
   superior — N es el número de faenas pendientes.
2. Las faenas se envían una por una. Si la conexión se corta a la mitad, **no pasa
   nada**: al volver a sincronizar se reintenta y el sistema **nunca duplica** una faena
   ya enviada.
3. Cuando el contador llegue a 0, todo está en la base de datos central (el administrador
   ya puede verlo en la consola).

**Recomendación operativa:** sincroniza al final de cada jornada o al volver a un punto
con señal; no dejes acumular muchos días.

## 1.6 Cerrar sesión

El botón **Salir** cierra tu sesión. No lo uses si aún tienes faenas sin sincronizar,
salvo indicación del administrador.

## 1.7 Problemas frecuentes (técnico)

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| "Correo o contraseña incorrectos" | Credenciales mal escritas | Verifica mayúsculas/espacios; usa el restablecimiento por código si la olvidaste |
| Mensaje de cuenta desactivada | El administrador desactivó tu cuenta | Contacta al administrador |
| Bloqueo "sin formulario asignado" | Tu usuario no tiene formato asignado | El administrador debe asignarte uno en 👤 Usuarios |
| Una especie/pescador no aparece en la lista | No está en la lista curada | Usa "Otro / proponer"; el administrador la aprobará |
| Sincronizar no baja el contador | Sin internet real, o error puntual | Verifica la conexión y reintenta; si persiste, reporta al administrador |

---

# Parte 2 — Consola de administración (administradores)

## 2.1 Acceso

La consola es una página web (URL proporcionada por tu organización, servida por HTTPS).
Inicia sesión con tu correo y contraseña de **ADMINISTRADOR**. La pantalla **🏠 Inicio**
muestra tarjetas de resumen (propuestas pendientes, duplicados, formulario vigente) con
accesos directos.

El menú lateral se organiza en tres grupos:

- **REVISAR:** 🔎 Duplicados · 📥 Propuestas de campo
- **CONFIGURAR:** ✏️ Catálogos · 🛠️ Formularios · 📑 Listas del formulario · 👤 Usuarios
- **DATOS:** 📤 Descargar datos · 🧹 Datos de prueba

## 2.2 🔎 Duplicados

Herramienta de limpieza de catálogos: detecta entradas que probablemente son la misma
(p. ej. "Jurel" / "jurel " / "Jurél") y permite **fusionarlas** conservando una entrada
"sobreviviente". La fusión repunta automáticamente todas las referencias históricas
(faenas, capturas, mediciones y listas curadas), así que no se pierde ningún dato. Las
decisiones tomadas quedan guardadas y no se vuelven a preguntar.

## 2.3 📥 Propuestas de campo

Aquí llegan las entradas que los técnicos propusieron desde la tablet ("Otro / proponer"):
especies, pescadores, embarcaciones, sitios. Para cada propuesta puedes **aprobar**
(entra al catálogo y a los selectores), **rechazar**, o **fusionar** con una entrada
existente si ya existía con otro nombre. Cada acción queda registrada en la bitácora de
cambios de catálogos (quién, qué y cuándo).

## 2.4 ✏️ Catálogos

Edición directa de los catálogos (especies, sitios, cooperativas, embarcaciones, artes de
pesca, etc.): crear entradas, corregir nombres, marcar aprobación. Solo las entradas
**aprobadas** aparecen en los selectores de la tablet. Desde aquí también se controla qué
catálogos aceptan propuestas de campo.

## 2.5 🛠️ Formularios (constructor)

Permite crear y publicar las **versiones del formulario** que la tablet renderiza:

- Cada formulario pertenece a un **formato** (p. ej. `BOCA_ALAMO_V2`) y tiene una
  **versión decimal que tú asignas** (p. ej. 0.8, 0.9, 1.0).
- Puedes agregar/quitar secciones y campos, marcar obligatorios, definir rangos de
  validación, condiciones de visibilidad ("mostrar solo si el arte es Piola") y campos
  repetibles (varias capturas, varias mediciones).
- A cada campo de lista se le asocia una **lista curada** (ver 2.6); la vista previa
  muestra las condiciones con nombres legibles, no códigos.
- **Publicar es irreversible para esa versión**: una versión publicada no se puede
  editar (garantiza que se sepa exactamente con qué formulario se capturó cada faena).
  Para cambiar algo, crea la siguiente versión y publícala.
- La tablet descarga automáticamente la última versión publicada del formato asignado al
  técnico la próxima vez que abra sesión con internet.

## 2.6 📑 Listas del formulario

Los catálogos completos son demasiado grandes/ruidosos para los selectores de la tablet.
Aquí se curan las **listas por formulario** (p. ej. `especies`, `carnada`, `pescadores`):

- Agrega o quita entradas buscándolas en el catálogo (un clic agrega).
- Asigna **importancia** para ordenar qué aparece primero en el selector.
- También se puede importar una lista completa por CSV.

## 2.7 👤 Usuarios

- **Crear usuario:** nombre, correo, contraseña inicial y **rol** (TECNICO /
  ADMINISTRADOR / ANALISTA). A los técnicos se les vincula su registro de técnico del
  catálogo (se puede crear el técnico ahí mismo) y a los analistas su **región**.
- **Asignar formulario:** cada técnico debe tener un **formato asignado**; sin él la
  tablet lo bloquea. Solo se ofrecen formatos con formulario publicado vigente.
- **Cambiar rol / desactivar cuenta:** desde la misma pantalla.
- **Contraseñas:** cada usuario restablece la suya por código enviado a su correo (desde
  la app o la consola); el administrador ya no fija contraseñas de terceros.

## 2.8 📤 Descargar datos

Dos modos de exportación (a Excel/CSV):

- **Consultas predefinidas:** faenas, capturas, mediciones, etc., con filtros de fecha,
  región y comunidad. Los identificadores se muestran **resueltos a nombres** (con opción
  "Mostrar ids").
- **🔧 Constructor:** elige una entidad base (p. ej. faena), agrega columnas de sus
  catálogos relacionados y registros hijos (como resumen —conteo/suma— o al detalle),
  y aplica **filtros por valor** (comunidad, región, cooperativa…). Puedes **elegir y
  renombrar columnas** y **guardar la consulta** para reutilizarla (privada o compartida
  con otros administradores).

## 2.9 🧹 Datos de prueba

Las capturas hechas con las cuentas de prueba (vinculadas al técnico **"PRUEBAS — no usar
en campo"**) se pueden previsualizar y borrar aquí, con doble confirmación. La
herramienta solo puede tocar las faenas de ese técnico de pruebas — no puede afectar
datos reales. También permite borrar una faena específica por su identificador.

## 2.10 Buenas prácticas del administrador

- Revisa **Propuestas de campo** con frecuencia: mientras una propuesta no se apruebe, no
  aparece en los selectores de los demás técnicos.
- Antes de publicar una nueva versión del formulario, revísala con la **vista previa** y
  pruébala con una cuenta de técnico de pruebas.
- Vigila el tamaño de la base de datos (límite del plan gratuito de Supabase: 500 MB).
- Mantén la disciplina de respaldos acordada (ver `PROD_ROLLOUT.md` y la respuesta 6.3
  de `Respuestas.md`).

---

# Parte 3 — Consola (analistas)

El rol **ANALISTA** entra a la misma consola web pero solo ve **🏠 Inicio** y
**📤 Descargar datos**:

- Las exportaciones quedan **limitadas automáticamente a la región asignada** a tu
  cuenta (aparece fija, no seleccionable).
- Dispones de las consultas predefinidas con filtros de fecha y comunidad; el constructor
  de consultas avanzado es exclusivo de administradores.
- Si necesitas datos de otra región o una consulta especial, solicítala a un
  administrador (puede compartir contigo el archivo exportado).

---

# Parte 4 — Sistema de reportes de radar M2 (personal autorizado)

Servicio independiente que genera y envía automáticamente, cada mes, el **Reporte de
Actividad del M2** (PDF) por cada sitio de radar (Loreto, Loreto 2, San Basilio, Islas
Marías, El Pardito, Espíritu Santo). Su **panel de administración web** permite:

- Gestionar los sitios y la **lista de destinatarios de correo por sitio**.
- Ver el **historial de reportes** generados por sitio y descargarlos.
- **Ejecutar manualmente** la generación de un sitio o de todos (además del envío
  automático mensual programado).
- Configurar los datos de comparación año contra año (línea base) por sitio.

Este servicio no usa las cuentas del sistema de bitácoras; su acceso lo administra quien
opere el servidor donde está instalado.
