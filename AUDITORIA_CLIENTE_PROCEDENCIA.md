# Revisión del cliente aislado y la procedencia

Fecha: 28 de octubre de 2026. Revisión estática y pruebas sin red. No se ejecutaron
crawlers contra sitios reales ni se modificaron documentos o estados históricos.

## Estado encontrado antes de los cambios

| Requisito | Estado previo | Falta detectada |
|---|---|---|
| Aislamiento por cliente | `CrawlerManager` ya usa `<root>/<cliente>/<país>/` para documentos, `_state/round_robin.yaml` y `_logs/`. `bootstrap` escribe planes por cliente. | Faltaba definir el nuevo cliente. No había que migrar ni reiniciar estados. |
| Reutilización de crawlers | `crawler_loader` y el menú buscaban módulos únicamente dentro del cliente elegido. | Un cliente nuevo sin copias de crawlers no podía seleccionarlos ni cargarlos. `bootstrap` descartaba `targets`, necesarios para Asamblea. |
| Sidecar Discovery | Los diez crawlers de `clients/veredictum/crawlers/ti` y `base_crawler` guardaban bytes directamente o delegaban en una función que lo hacía. Sus resultados `downloaded` no tenían URL final ni metadatos de archivo. | No había forma fiable de generar el sidecar desde `CrawlerManager` después del hecho. La URL final debe tomarse de la respuesta de descarga en cada crawler. |
| Sidecar Batch | Batch ya aislaba estado, verificaba documentos y guardaba URL final, fecha y hash en SQLite. | Faltaba el archivo `.source.json` junto al original. No se cambió el procesamiento de manifiestos. |
| Archivos existentes | Los crawlers podían sobrescribir nombres en modo completo. | La escritura debía rechazar nombres existentes. Los documentos históricos no tienen procedencia verificable para crearles sidecars retroactivos. |

## Cambios aplicados

- `clients/costa_rica` contiene inventario y configuración propios. `crawler_provider`
  y `classifier_provider` reutilizan módulos existentes sin copiarlos; solo se
  comparte código. Los documentos y el scheduler usan siempre el nombre del cliente
  solicitante, no el proveedor del crawler.
- `bootstrap` conserva `targets` en el plan generado, de modo que Asamblea pueda
  recibir sus URL sin lógica especial para el nuevo cliente.
- `core.source_sidecar` guarda bytes originales y `<documento>.source.json` con
  `source_url` (URL final observada), `downloaded_at_utc`, `sha256` y `size_bytes`.
  Las publicaciones usan enlaces exclusivos; un archivo previo no se reemplaza.
  Discovery retorna `downloaded` solo después de guardar original y sidecar.
- Batch llama al mismo escritor de sidecar después de su descarga atómica y antes
  de registrar `descargado`. La URL procede de la respuesta final; no se construye
  a partir del inventario o del nombre del archivo.

## Comprobación

`venv/bin/python -m unittest discover -s tests -q`: 41 pruebas correctas. Cubren
aislamiento de plan y scheduler, reutilización del mismo módulo crawler, bytes
originales, URL final después de redirección, hash, tamaño, timestamp UTC,
protección contra sobrescritura, fallo al publicar sidecar y el Batch existente.
Todas las pruebas usan una raíz temporal y no contactan Internet.

Una prueba del CLI con raíz temporal ejecutó `plan` y `status`: apareció el plan
de `costa_rica/ti`, no se creó scheduler, no apareció una ruta Veredictum y no se
crearon PDF. `compileall` y `git diff --check` no reportaron problemas.

## Límite deliberado

Los documentos ya presentes no reciben sidecars retroactivos: su fecha y URL
final de descarga original no pueden recuperarse con certeza de los bytes. La
correctitud de extracción de los portales requiere pruebas de red separadas; no
se hizo crawling real en esta entrega.

## Preparación sin descarga

En la VM configurada, usar el entorno virtual con las dependencias instaladas:

```bash
cd /srv/metacrawler/app
export METACRAWLER_DATA_ROOT=/media/sf_fileforge-data/metacrawler
./venv/bin/python runner.py plan --client costa_rica --country ti
./venv/bin/python runner.py status
```
