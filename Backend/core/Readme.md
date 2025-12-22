🕷️ Metacrawler

Metacrawler es un motor de crawling modular, persistente y multi-cliente, diseñado para descargar documentos desde fuentes oficiales de forma segura, escalable y humana.

Funciona como la capa de adquisición de datos para FileForgeAI y otros sistemas que requieran ingesta documental confiable.

Aunque nació dentro del ecosistema de FileForgeAI, Metacrawler está diseñado como un proyecto independiente y reutilizable, aplicable a distintos clientes, países y dominios (legal, institucional, académico, corporativo, financiero, etc.).

🎯 Objetivo

Resolver de forma definitiva los problemas clásicos del crawling:

Bloqueos por comportamiento agresivo

Descargas duplicadas

Crawlers rígidos y difíciles de mantener

Mezcla de lógica de descarga con lógica de negocio

Falta de estado persistente

Scripts que no escalan a múltiples clientes o países

Metacrawler NO interpreta ni clasifica documentos.
Su única responsabilidad es:

Descargar documentos de forma correcta, organizada y repetible.

La clasificación semántica ocurre después, en FileForgeAI u otros sistemas consumidores.

🧠 Principios de diseño
1. 🧩 Modularidad total

Soporta múltiples clientes

Soporta múltiples países por cliente

Soporta múltiples fuentes por cliente

La lógica específica vive en módulos, no en el core

2. 🧍‍♂️ Comportamiento humano

Crawling round-robin por fuente

Una descarga efectiva por fuente en cada ciclo

No martilla una sola institución

Ritmo natural de requests, no agresivo

3. 💾 Estado persistente

Todo el progreso se guarda en disco

El crawler puede:

continuar

reiniciarse

descargar solo documentos nuevos

El estado es independiente por cliente, país y fuente

4. 🔁 Anti-duplicados transversal

El deduplicado es global

Se aplica a cualquier crawler

Evita duplicados incluso entre distintas fuentes

5. 🧠 Separación estricta de responsabilidades

Metacrawler descarga

FileForgeAI procesa y clasifica

Ningún crawler decide qué tipo de documento es

🗂️ Estructura del proyecto (core)
metacrawler/
├── bootstrap_sources.py      # Genera sources.yaml a partir de URLs
├── runner.py                 # Interfaz CLI (cliente / país / fuentes)
├── crawler_manager.py        # Orquestador de crawling
├── crawler_loader.py         # Resolución dinámica de crawlers
├── base_crawler.py           # Fallback genérico
├── utils/
│   └── round_robin.py        # Scheduler persistente
├── config/
│   └── itu_map.yaml          # Mapa ITU opcional
├── sources.yaml              # Generado automáticamente (NO editar)
└── README.md

📁 Estructura OBLIGATORIA de clientes y URLs

⚠️ Esta sección es normativa.
El runner asume esta estructura y no escanea recursivamente.

Backend/clients/
├── <cliente>/
│   ├── <pais>-urls.txt
│   ├── <otro-pais>-urls.txt
│   └── ...
├── <otro_cliente>/
│   └── <pais>-urls.txt

Reglas estrictas

Un cliente = una carpeta

Los archivos *-urls.txt DEBEN estar dentro de la carpeta del cliente

El runner:

❌ no busca en clients/

❌ no baja niveles

❌ no infiere clientes por archivos

Si un archivo está fuera de su carpeta de cliente, no existe para el runner

Esto no es una limitación accidental, es una decisión de diseño para evitar ambigüedad y errores silenciosos.

🧭 Conceptos clave
Cliente

Un cliente es cualquier entidad para la cual se descargan documentos:

Veredictum (cliente interno)

Instituciones públicas

Bancos

Empresas privadas

Multinacionales

Cada cliente tiene:

Sus propias URLs

Sus propios crawlers

Su propia estructura de datos

Estados completamente aislados

País (opcional)

Algunos clientes son multi-país (ej. Veredictum).
Otros son mono-país (ej. una institución local).

Se puede usar nomenclatura ITU:

TI → Costa Rica

XA → México

El uso de ITU es opcional, pero recomendado para clientes multi-país.

Fuentes

Una fuente representa una unidad lógica de descarga:

Asamblea Legislativa

Gaceta

Poder Judicial

Instituciones

Repositorios académicos

Una fuente puede:

Tener una sola URL

Tener múltiples URLs (targets)

Ser recorrida parcial o totalmente

📦 Flujo general de ejecución

El usuario ejecuta runner.py

Selecciona un cliente

Selecciona uno o más archivos *-urls.txt (países)

Por cada archivo:

Se ejecuta bootstrap_sources.py

Se genera sources.yaml

El usuario selecciona:

todas las fuentes

o fuentes específicas

El CrawlerManager:

resuelve el crawler correcto

inyecta contexto (paths, estado, modo)

ejecuta crawling round-robin

El proceso puede detenerse y reanudarse en cualquier momento

💽 Almacenamiento

Todo el output vive fuera del código, en disco persistente:

fileforge-data/metacrawler/
├── downloads/
│   └── <cliente>/<pais>/<fuente>/
├── state/
│   └── <cliente>/<pais>/<fuente>.json
├── scheduler/
│   └── round_robin.yaml
└── logs/


Esto permite:

Persistencia real

Reprocesar sin volver a descargar

Separar datos de lógica

🔒 Ética y anti-bloqueo

Metacrawler está diseñado para:

Respetar infraestructuras públicas

Minimizar carga en servidores

Evitar patrones de ataque

Simular navegación humana legítima

No está pensado para scraping agresivo ni evasión maliciosa.

🔗 Relación con FileForgeAI

Metacrawler

Funciona de forma independiente

Produce PDFs organizados

No interpreta documentos

FileForgeAI

Consume el output de Metacrawler

Realiza OCR, normalización, feature engineering y clasificación

🚧 Estado del proyecto
Implementado

✔️ Arquitectura definida

✔️ Bootstrap funcional

✔️ Runner interactivo

✔️ Scheduler Round-Robin persistente

✔️ Crawler Manager operativo

✔️ Crawlers específicos y genéricos funcionales

Deuda técnica identificada (consciente)

Reducir tamaño del CrawlerManager

Extraer lógica de:

CLI

Resolución de fuentes

Manejo de estado

Mejorar observabilidad

Refinar scheduler (prioridades, backoff)

Nada de esto bloquea el uso actual.

🧠 Filosofía

“Descargar bien es más importante que descargar rápido.”

Metacrawler prioriza:

Correctitud

Persistencia

Escalabilidad

Mantenibilidad

por encima de velocidad bruta.