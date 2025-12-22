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
