# Diagrama de Arquitectura — Sistema de Bitácoras Pesqueras Pronatura Noroeste

Diagramas UML en notación **Mermaid** (se renderizan automáticamente en GitHub, VS Code
y la mayoría de visores Markdown). Actualizado al 2026-07-09.

---

## 1. Diagrama de componentes (vista general del sistema)

```mermaid
flowchart TB
    subgraph CAMPO["📱 Campo (offline)"]
        APP["App de captura<br/><i>Expo / React Native (Android · iOS)</i>"]
        SQLITE[("SQLite local<br/>outbox + caché de<br/>formulario y catálogos")]
        APP <--> SQLITE
    end

    subgraph SUPABASE["☁️ Supabase (backend)"]
        AUTH["Auth (GoTrue)<br/>correo + contraseña"]
        POSTGREST["PostgREST<br/>API REST automática"]
        PG[("PostgreSQL<br/>esquema public<br/>16 migraciones + RLS")]
        RPC["RPC crear_faena_completa<br/><i>atómica e idempotente</i>"]
        POSTGREST --> PG
        RPC --> PG
        AUTH --> PG
    end

    subgraph VPS["🖥️ VPS (Docker)"]
        CADDY["Caddy<br/>HTTPS automático"]
        CONSOLA["Consola de administración<br/><i>Streamlit (Python)</i>"]
        CADDY --> CONSOLA
    end

    subgraph M2["🛰️ Servicio de reportes M2 (independiente)"]
        FLASK["Panel admin<br/><i>Flask + HTMX</i>"]
        SCHED["APScheduler<br/>cron mensual"]
        PIPE["Pipeline: httpx → pandas →<br/>matplotlib → Jinja2 → WeasyPrint"]
        SQLITE2[("SQLite<br/>sitios · destinatarios ·<br/>historial · líneas base")]
        FLASK --> SQLITE2
        SCHED --> PIPE
        PIPE --> SQLITE2
    end

    ADMIN["👤 Administrador / Analista<br/>(navegador)"] --> CADDY
    TECNICO["👤 Técnico de campo"] --> APP

    APP -- "login (JWT)" --> AUTH
    APP -- "descarga formulario,<br/>catálogos y listas" --> POSTGREST
    APP -- "sincroniza faenas" --> RPC

    CONSOLA -- "SQL directo (psycopg2)<br/>DATABASE_URL" --> PG
    CONSOLA -- "crear usuarios<br/>(service-role, solo servidor)" --> AUTH

    PS["🌐 API ProtectedSeas M2"] --> PIPE
    PIPE -- "PDF por sitio" --> SMTP["📧 Servidor SMTP"]
    SMTP --> DEST["Destinatarios por sitio"]
```

**Puntos clave:** la app nunca toca la base directamente — todo pasa por Auth + PostgREST
+ la RPC, gobernados por RLS. La consola usa conexión directa a Postgres y la llave
service-role, que viven solo en el servidor. El servicio M2 es completamente independiente
del backend de bitácoras.

---

## 2. Diagrama de despliegue

```mermaid
flowchart LR
    subgraph TABLET["Tablet Android/Huawei (iOS posible)"]
        APK["APK capture-app<br/>(EAS build, sin Play Store)"]
    end

    subgraph CLOUD["Supabase (aws-us-west-1)"]
        PROD[("Proyecto PROD<br/>Postgres + Auth + PostgREST")]
    end

    subgraph SERVIDOR["VPS de la organización"]
        direction TB
        D1["contenedor: caddy<br/>puertos 80/443, TLS Let's Encrypt"]
        D2["contenedor: consola (Streamlit)"]
        VOL[("volumen: decisions/<br/>decisiones de deduplicación")]
        D1 --> D2
        D2 --> VOL
        D3["contenedor: m2-report-service<br/>(Flask + APScheduler)"]
    end

    DEV[("Proyecto DEV<br/>Supabase (aws-us-east-1)<br/>pruebas y desarrollo")]

    APK -- "HTTPS" --> PROD
    D2 -- "HTTPS / SQL con TLS" --> PROD
    D3 -- "HTTPS" --> PSAPI["API ProtectedSeas"]
    D3 -- "SMTP/TLS" --> MAIL["Relay de correo"]

    GH["GitHub org PronaturaNoroeste<br/>4 repositorios (main)"] -. "git pull +<br/>docker compose up -d --build" .-> SERVIDOR
    EAS["Expo EAS<br/>compilación de APK/iOS"] -. "APK firmado" .-> TABLET
```

---

## 3. Diagrama de secuencia — captura offline y sincronización

```mermaid
sequenceDiagram
    actor T as Técnico
    participant A as App (tablet)
    participant O as Outbox (SQLite local)
    participant AU as Supabase Auth
    participant PR as PostgREST
    participant DB as PostgreSQL (RPC + RLS)

    Note over T,DB: Con internet (una vez)
    T->>A: correo + contraseña
    A->>AU: login
    AU-->>A: JWT (sesión)
    A->>PR: GET formulario publicado (formato asignado)
    A->>PR: GET catálogos aprobados + listas curadas
    PR-->>A: definición JSON + opciones (se cachean en SQLite)

    Note over T,O: Sin internet (en el mar / en campo)
    loop cada faena
        T->>A: llena el formulario dinámico
        A->>A: motor de visibilidad y validación (visible_si, rangos)
        A->>A: buildPayload (respuestas → payload RPC, kg→gr)
        A->>O: encolar faena (UUID generado en el cliente)
        O-->>T: ✓ Faena guardada en el dispositivo
    end

    Note over A,DB: Con internet de nuevo
    T->>A: toca "Sincronizar (N)"
    loop por cada faena pendiente
        A->>DB: crear_faena_completa(payload) [JWT]
        DB->>DB: transacción atómica: faena + hijos<br/>(idempotente: mismo UUID ⇒ no duplica)
        DB-->>A: OK
        A->>O: quitar de la cola
    end
    A-->>T: 0 sin sincronizar
```

---

## 4. Diagrama de secuencia — publicación de un formulario

```mermaid
sequenceDiagram
    actor AD as Administrador
    participant C as Consola (Streamlit)
    participant DB as PostgreSQL
    actor TC as Técnico (tablet)

    AD->>C: 🛠️ Formularios: editar borrador (versión decimal, p. ej. 0.9)
    C->>DB: guardar formulario (estado = borrador)
    AD->>C: publicar
    C->>DB: UPDATE estado = 'publicado'
    Note over DB: trigger: la definición publicada<br/>queda inmutable
    TC->>DB: siguiente login con internet
    DB-->>TC: última versión publicada del formato asignado
    Note over TC: cada faena capturada estampa<br/>formulario_id + version (0.9)
```

---

## 5. Modelo entidad–relación (núcleo)

```mermaid
erDiagram
    formulario ||--o{ faena : "capturada con (id + version)"
    cat_formato_origen ||--o{ formulario : "ámbito"
    cat_formato_origen ||--o{ lista_opcion : "listas curadas"
    usuario }o--|| cat_tecnico : "vinculado a"
    usuario }o--o| cat_formato_origen : "formulario asignado"
    usuario }o--o| cat_region : "candado de región"

    faena ||--o{ faena_especie_objetivo : ""
    faena ||--o{ faena_arte : ""
    faena ||--o{ captura : ""
    faena ||--o{ medicion : ""
    faena ||--o{ carnada : ""
    faena ||--o{ interaccion_etp : ""
    faena ||--o{ gasto : ""
    faena ||--o{ valor_campo_faena : "campos custom"
    faena ||--o| aportacion_imss : "Nota de Pago"
    faena ||--o{ recurso_ahorro : "Nota de Pago"

    captura ||--o{ medicion : "opcional"
    cat_especie ||--o{ captura : ""
    cat_especie ||--o{ medicion : ""
    cat_comunidad ||--o{ faena : ""
    cat_sitio_pesca ||--o{ faena : ""
    cat_embarcacion ||--o{ faena : ""
    cat_pescador ||--o{ faena : "capitán"
    cat_tecnico ||--o{ faena : ""
    cat_tipo_arte ||--o{ faena_arte : ""
    campo_formulario ||--o{ valor_campo_faena : ""
```

El detalle completo de columnas, tipos y restricciones está en
[`Diccionario_de_Datos.md`](Diccionario_de_Datos.md).
