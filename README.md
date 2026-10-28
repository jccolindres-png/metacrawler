# 🕷️ Metacrawler

**Metacrawler** es un motor de crawling modular, persistente y multi-cliente, diseñado para descargar documentos desde fuentes oficiales de forma segura, controlada y auditable.

Nació como la capa de adquisición de datos para proyectos legales y documentales (como FileForge y Veredictum), pero está diseñado para funcionar como un sistema independiente y reutilizable.

---

## 🎯 Objetivo

Resolver problemas clásicos del crawling institucional:

- Bloqueos por comportamiento agresivo
- Descargas duplicadas
- Crawlers rígidos y difíciles de mantener
- Mezcla de lógica de descarga, clasificación y negocio
- Falta de control y auditabilidad

Metacrawler separa claramente **qué se descarga**, **cómo se descarga** y **quién lo consume**.

---

## 🧠 Principios de diseño

- **Modular**: cada crawler es independiente
- **Persistente**: el estado se guarda entre ejecuciones
- **Determinista**: una acción efectiva por crawler por ciclo
- **Humano-friendly**: menús interactivos y selección explícita
- **Multi-cliente**: múltiples consumidores con reglas distintas
- **Auditabilidad primero**: logs, estados y deduplicación persistente

---

## 🏗️ Arquitectura general

metacrawler/
├── Backend/
│ ├── core/ # Motor del crawler
│ │ ├── crawler_manager.py
│ │ ├── crawler_loader.py
│ │ ├── bootstrap_sources.py
│ │ ├── classifiers/ # Clasificación de URLs → fuentes
│ │ ├── utils/ # Menús, dedupe, round-robin, etc.
│ │ └── config/
│ └── config/
├── clients/ # Clientes y sus crawlers
│ └── <cliente>/
│ ├── crawlers/
│ │ └── <país>/
│ │ └── <fuente>.py
│ ├── classifier.py
│ └── <país>-urls.txt
├── downloads/ # Datos y estado (NO versionado)
├── runner.py # Punto de entrada
└── README.md


---

## 🚀 Flujo de ejecución

1. **Selección de cliente**
2. **Selección de país (URLs)**
3. **Bootstrap**
   - Clasifica URLs
   - Genera `sources.yaml`
4. **Selección de fuentes**
5. **Ejecución controlada**
   - Round-robin persistente
   - Un crawler por iteración
6. **Descarga con deduplicación**
7. **Logs y estado persistente**

---

## 📦 Descargas y estado

Todo el estado y los datos viven **fuera del código**, en:

downloads/
├── <cliente>/
│ └── <país>/
│ ├── <fuente>/
│ ├── _logs/
│ └── _state/
└── _state/
└── dedupe_store.json


Esto permite:
- Reinicios seguros
- Auditoría completa
- Reprocesamiento controlado
- Separación total código / datos

---

## 🧩 Crawlers

Cada crawler es un módulo Python simple que implementa uno de estos entrypoints:

```python
def download_one(ctx): ...
# o
def run(ctx): ...

El crawler no decide:

    ritmo

    volumen

    orden

Eso lo controla el CrawlerManager.
🔒 Deduplicación

La deduplicación es:

    por contenido (hash SHA-256)

    persistente

    transversal a clientes y fuentes

Un documento idéntico nunca se guarda dos veces, aunque venga de URLs distintas.
👥 Clientes

Un cliente define:

    sus crawlers

    su clasificador

    sus URLs de entrada

Ejemplo:

clients/veredictum/
├── classifier.py
├── ti-urls.txt
└── crawlers/

Esto permite que múltiples proyectos usen el mismo motor sin interferirse.
🛠️ Requisitos

    Python 3.10+

    Linux recomendado

    Virtual environment (no incluido en el repo)

Instalación:

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

Ejecución:

python runner.py

## Configuración y operación segura

`METACRAWLER_DATA_ROOT` es la configuración canónica y tiene prioridad sobre el
valor predeterminado. El directorio configurado debe existir y ser escribible;
Metacrawler falla explícitamente si no lo es. `.env.example` documenta el patrón
sin guardar rutas locales. En esta VM, `scripts/metacrawler-vm` activa
`/media/sf_fileforge-data/metacrawler` y muestra la raíz efectiva al arrancar.

La disposición de ejecución es `<root>/<cliente>/<país>/{<fuente>,_plans,_state,_logs}`;
el deduplicador global permanece en `<root>/_state/dedupe_store.json`. Los planes
generados viven en `_plans/sources.yaml`, nunca en el árbol de código.

Comandos sin crawling:

```bash
scripts/metacrawler-vm validate-config
scripts/metacrawler-vm status
scripts/metacrawler-vm plan --client veredictum --country ti
scripts/metacrawler-vm reset-state --client veredictum --country ti --yes
```

`reset-state` requiere confirmación explícita. `status` y `plan` no importan ni
ejecutan crawlers. Los resultados antiguos (`downloaded`, `skipped`, `failed`) se
adaptan al contrato estructurado; los eventos operativos se escriben también como
JSONL. Muchos crawlers institucionales aún convierten excepciones en `skipped`, por
lo que arrancar correctamente el core no certifica su extracción ni distingue la
causa interna que esos módulos ocultaron.

⚠️ Estado del proyecto

Metacrawler está en desarrollo activo.

    La arquitectura es estable

    Los crawlers se agregan de forma incremental

    La API interna puede evolucionar

No es una librería genérica aún, sino un motor especializado.
🤝 Contribuciones

Este proyecto es joven.
Las contribuciones, ideas y revisiones son bienvenidas, pero el foco actual es consolidar el core.
📄 Licencia

Pendiente de definir.

✍️ Autor

JC Colindres
Primer proyecto público.
Construido con paciencia, necesidad real y muchas horas de depuración.

## Modo Batch para leyes de Costa Rica

Batch se ejecuta por separado de Discovery. Admite `veredictum/ti` con objetivos
`jurisdiccion: "CR"`. Su base SQLite y sus documentos viven bajo
`<METACRAWLER_DATA_ROOT>/veredictum/ti/_batch/`; no modifica los inventarios,
planes, cursores, logs ni el deduplicador global de Discovery.

El manifiesto JSON requiere `{ "objetivos": [...] }`. Cada objetivo necesita
`target_id` y `jurisdiccion`. Puede incluir `numero_ley`, `titulo_buscado`,
`rama`, `prioridad`, `portal_oficial` y `url_referencia_oficial` (también se admite
`null`). Si faltan número y título, queda en revisión hasta completar la identidad.
CSV con las mismas columnas es opcional. Una URL ausente queda pendiente;
se asocia manualmente después de verificarla. La importación es transaccional e
idempotente; un `target_id` existente con datos diferentes causa error sin alterar
el estado anterior. Una URL fuera de los dominios admitidos se conserva para
revisión y nunca se consulta automáticamente.

```bash
# Con METACRAWLER_DATA_ROOT configurado en la raíz de datos existente:
python runner.py batch import --manifest ./veredictum_cr_batch01_manifest.json
python runner.py batch simulate

# Solo después de revisar la simulación y las URL oficiales:
python runner.py batch resolve --target-id ID --url https://sinalevi.go.cr/ruta-verificada
python runner.py batch identify --target-id ID --numero-ley 123 --titulo-buscado "Ley de ejemplo"
python runner.py batch run --target-id ID
python runner.py batch history --target-id ID
```

`batch import` y `batch simulate` no hacen solicitudes de red ni descargan archivos.
`batch run` es la única orden que descarga. Acepta solo HTTPS en dominios oficiales
de PGR/SINALEVI, Asamblea e Imprenta; comprueba cada redirección. Una ficha HTML
con un solo enlace a PDF puede resolverse; una ficha ambigua queda para revisión.
En el portal SINALEVI nuevo, admite la vista de texto completo (`param3=1`);
fichas y artículos aislados quedan para revisión.
Comprueba el número y título solicitados en el documento. Un PDF escaneado, sin
texto extraíble o incompleto queda en `requiere revisión`; no se marca descargado.
Se registran URL original y final, fecha UTC, versión normativa publicada cuando
está disponible, versión HTTP o fecha de captura, estado, motivo, ruta y SHA-256.
Los estados son `pendiente`, `resuelto`,
`descargado`, `omitido`, `fallido` y `requiere revisión`. Los fallos son reintentables;
el historial conserva cada transición y el hash del manifiesto de importación.
`batch run` también puede ejecutarse sin `--target-id` para procesar todos los
objetivos con URL. Los archivos se publican de manera atómica y sin sobrescritura.

La validación es deliberadamente conservadora: una coincidencia dudosa requiere
revisión humana. No hay generación automática de URL a partir de números de ley.
Instale las dependencias de `requirements.txt` antes de ejecutar descargas de PDF.

La auditoría detallada está en [AUDITORIA_BATCH.md](AUDITORIA_BATCH.md).

## Colección independiente `costa_rica`

El cliente `costa_rica` usa `ti` como código de país y tiene inventario propio en
`clients/costa_rica/ti-urls.txt`. Su configuración reutiliza los módulos de crawlers
y el clasificador existentes mediante un proveedor explícito, sin copiarlos. Sus
planes, estado, logs y documentos se guardan exclusivamente bajo
`<METACRAWLER_DATA_ROOT>/costa_rica/ti/`.

En la VM configurada, estos comandos preparan e inspeccionan la colección **sin
ejecutar crawlers ni descargar documentos**:

```bash
cd /srv/metacrawler/app
export METACRAWLER_DATA_ROOT=/media/sf_fileforge-data/metacrawler
./venv/bin/python runner.py plan --client costa_rica --country ti
./venv/bin/python runner.py status
```

Cada nueva descarga Discovery o Batch genera `<documento>.source.json` junto al
original. Contiene `source_url` (URL final de la respuesta), `downloaded_at_utc`,
`sha256` y `size_bytes`. No se cambian bytes ni se crean valores de procedencia
para documentos históricos que ya existían. Un nombre de archivo existente no se
sobrescribe, incluso en modo completo.

### Primera ejecución controlada de PGR y SINALEVI

El plan de `costa_rica/ti` incluye `pgr` y `sinalevi`. Cada invocación siguiente
selecciona solo una fuente y permite como máximo una descarga. Las rutas de datos
se mantienen bajo `<METACRAWLER_DATA_ROOT>/costa_rica/ti/`.

```bash
cd /srv/metacrawler/app
export METACRAWLER_DATA_ROOT=/media/sf_fileforge-data/metacrawler
./venv/bin/python runner.py plan --client costa_rica --country ti

run_one() {
./venv/bin/python - "$1" <<'PY'
import os
import sys
from pathlib import Path
import runner
from core.crawler_manager import CrawlerManager

source_id = sys.argv[1]
plan = Path(os.environ["METACRAWLER_DATA_ROOT"]) / "costa_rica/ti/_plans/sources.yaml"
manager = CrawlerManager("costa_rica", "ti", only_source=source_id, plan_path=plan)
manager.select_mode_interactively = lambda: "incremental"
manager.run()
PY
}

run_one pgr
run_one sinalevi
```

SINALEVI consulta la búsqueda sencilla de normativa paginada y solicita el PDF
al exportador oficial. Las búsquedas predeterminadas son `ley`, `decreto`,
`reglamento`, `acuerdo` y `resolución`; otras clases no quedan cubiertas
automáticamente. El estado anterior basado en índices del portal antiguo se
conserva sin migrarlo y requiere revisión manual si existe.
