# Auditoría de adquisición y entrega Batch

Fecha: 28 de octubre de 2026. Revisión estática del repositorio y de las páginas
institucionales citadas abajo. No se ejecutaron crawlers ni descargas del corpus.

## Flujo Discovery actual

1. `runner.py` elige cliente y archivo `ti-urls.txt`; `bootstrap_sources.py`
   extrae URL, llama al clasificador y escribe el plan `_plans/sources.yaml`.
2. `CrawlerManager` recibe las fuentes elegidas, crea una tarea por **fuente**
   en `_state/round_robin.yaml`, y entrega `base_urls`, `targets`, `download_dir`
   y `state_file` al crawler. Cada ciclo llama una vez a cada fuente seleccionada.
3. Los crawlers recorren sus páginas y seleccionan el primer PDF que cumplen
   sus heurísticas. La mayoría guardan directamente con `Path.write_bytes` y
   devuelven cadenas `downloaded` o `skipped`; `normalize_result` las adapta.
4. El scheduler guarda cursor, último resultado, ejecuciones y `retry_at`.
   Cada crawler guarda además su estado en `_state/<fuente>.json`. Los archivos
   quedan en `<root>/veredictum/ti/<fuente>/`; los eventos en `_logs/*.jsonl`.

## Problemas encontrados

| Gravedad | Evidencia | Consecuencia y tratamiento |
|---|---|---|
| Alta | `sinalevi.py`: tras excepción de página/PDF, respuesta inválida o enlace ausente escribía `current_n` en su estado | Podía omitir permanentemente un índice. Corregido: conserva índice y devuelve `failed` o `manual_review`. Pruebas de reintento y archivo incompleto. Los índices ya omitidos históricamente requieren una revisión separada del cursor; esta corrección no reescribe estados anteriores. |
| Alta | `gaceta.py:104-110`, `tramites.py:85-100`, `poder_judicial.py:55-92` | También avanzan fecha/índice después de fallos; permanecen como deuda de Discovery porque modificar sus reglas sin verificar sus portales alteraría su comportamiento. No se reutilizan en Batch. |
| Alta | `asamblea.py:89-99`, `pgr.py:93-100`, `gaceta.py:140`, y varios crawlers de repositorios | Excepciones se convierten en `skipped` y los PDF se escriben directamente. Un fallo puede parecer ausencia de documento, y un corte puede dejar un archivo parcial que incremental salta por existir. Batch usa estados explícitos, límite de tamaño, comprobación de PDF y publicación atómica. |
| Alta | `Backend/core/utils/dedupe.py:75-97` | Deduplica solo por hash, pero guarda archivo y JSON sin transacción ni sustitución atómica; además los crawlers inspeccionados no lo llaman. No es seguro compartirlo con Batch. Batch deduplica por identidad y SHA-256 en su propia base. |
| Media | `bootstrap_sources.py:70-82` y `classifiers/master.py:66-71` | Una excepción de clasificación se silencia y una URL sin `source_id` se descarta sin reporte. El clasificador usa coincidencia de subcadenas del dominio. Batch valida hosts exactos y deja URL desconocidas en revisión sin consultarlas. |
| Media | `round_robin.py:62-78,85-99` | La identidad de tarea omite `target_id`; `retry_at` se almacena pero `next()` no lo considera. No sirve como cola por documento. Batch usa `target_id` como clave persistente y permite reintentos sin borrar objetivos. |
| Media | `pgr.py:14,125-181`, `sinalevi.py:9-12` | El crawler PGR busca publicaciones por palabras clave, no leyes por identidad; SINALEVI usa un índice numérico supuesto. En el plan actual, el clasificador asigna sus URL a `pgr`, así que `sinalevi` ni siquiera se ejecuta automáticamente. Batch no fabrica rutas a partir del número de ley. |

## Comprobación de fuentes oficiales

- La [PGR anunció el traslado de SCIJ/SINALEVI a `sinalevi.go.cr`](https://www.pgr.go.cr/) desde el 20 de julio. La [página institucional de SINALEVI](https://www.pgr.go.cr/servicios/sinalevi/) enlaza al nuevo portal. El inventario Discovery todavía contiene `pgr.go.cr/scij/` y `pgrweb.go.cr/scij/`; el primero es el sitio institucional y el segundo es la dirección anterior del servicio. No se cambió el inventario para preservar Discovery.
- En el portal nuevo, la [vista de texto completo de una norma](https://sinalevi.go.cr/ResultadosNormativa/Informacion?param1=69312&param2=&param3=1&param4=) usa `ResultadosNormativa/Informacion` con `param3=1`; la [ficha](https://sinalevi.go.cr/ResultadosNormativa/Informacion?param1=27926&param2=145028&param3=2) usa `param3=2` y los artículos usan `param3=3`. Batch admite la primera solo si verifica identidad y texto; las vistas parciales quedan en revisión.
- El [portal oficial de La Gaceta](https://www.imprentanacional.go.cr/diarios_oficiales/index.aspx) sigue en Imprenta Nacional. El crawler construye `/gaceta/cgi-bin/search.pl`; la página institucional presenta un buscador distinto. No se pudo confirmar que ese endpoint construido siga operativo, por lo que no se usa en Batch.
- La [Asamblea mantiene una consulta de leyes por número o título](https://www.asamblea.go.cr/Centro_de_informacion/Consultas_SIL/SitePages/ConsultaLeyes.aspx). Su crawler Discovery inspecciona bibliotecas de PDF generales, no ese servicio de identidad normativa.
- Los demás dominios del inventario no fueron certificados URL por URL. La validez del dominio no demuestra que una ruta concreta entregue la norma pedida. Batch siempre valida el documento obtenido y deja lo incierto en revisión.

## Diseño implementado

`Backend/core/batch.py` usa únicamente la raíz de datos configurada y guarda
`_batch/batch.sqlite3` y `_batch/documents/`. La importación JSON/CSV valida todos
los objetivos antes de escribir y usa una transacción. Una repetición idéntica no
altera estados; un conflicto aborta todo. La simulación consulta la base sin red.

La ejecución serializa procesos con un bloqueo de archivo. Comprueba dominio HTTPS
en cada salto, tamaño y tipo de respuesta. Para PDF exige cabecera, EOF y texto
extraíble; para HTML solo admite una ruta normativa reconocible. Una ficha con un
único enlace oficial de documento puede conducir a un PDF. Comprueba número de ley
y título en el contenido inicial antes de guardar. Usa SHA-256 y ruta derivada de
`target_id` más hash; un enlace exclusivo publica el archivo completo sin pisar
otro. SQLite registra URL inicial/final, fecha UTC, versión normativa publicada,
versión HTTP o fecha de captura,
estado, motivo, ruta y hash. Un fallo de red deja el objetivo reintentable.
Una tabla de eventos conserva las transiciones, incluso cuando un reintento termina
correctamente, y registra el SHA-256 del manifiesto que originó cada objetivo.

Esta validación favorece evitar falsos positivos; documentos escaneados o formatos
no reconocidos requieren revisión. La resolución de objetivos sin URL es manual
mediante `batch resolve`; los objetivos sin número ni título esperan `batch identify`.
Una URL oficial no equivale por sí misma a documento
verificado. No se cambió `runner.py` sin argumentos, los clientes, scheduler,
directorios Discovery ni estados históricos.

## Verificación

`venv/bin/python -m unittest discover -s tests -q`: 35 pruebas, todas correctas.
Las pruebas interceptan la red y cubren importación, idempotencia, conflicto
transaccional, simulación, identidad, enlace inequívoco, redirección externa,
descarga incompleta, reintento y regresión del cursor SINALEVI. No se usó el
manifiesto real de 84 leyes: el archivo no está en el repositorio ni en el espacio
de trabajo disponible. Cuando esté disponible, los comandos de README importan y
simulan sus objetivos sin descargar documentos.
