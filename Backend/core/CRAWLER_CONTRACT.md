# CRAWLER CONTRACT — METACRAWLER

Este documento define el **CONTRATO OBLIGATORIO** que **TODO crawler**
debe cumplir para poder ejecutarse dentro del sistema de Round Robin.

Este contrato existe para:
- Evitar bloqueos de IP
- Evitar sobrecarga de sitios institucionales
- Garantizar comportamiento predecible
- Proteger al operador del sistema

NO es opcional.
NO es una sugerencia.
NO se negocia.

---

## 1. PRINCIPIO FUNDAMENTAL

👉 **UN crawler = UNA acción mínima por ejecución**

El crawler **NO debe intentar “aprovechar la sesión”**.
El sistema está diseñado para **operar por días**, no por minutos.

---

## 2. REGLAS OBLIGATORIAS (HARD RULES)

### 2.1 Descarga máxima

- ✅ Un crawler puede descargar **COMO MÁXIMO 1 archivo** por ejecución.
- ❌ Está prohibido descargar más de 1 archivo en una sola ejecución.
- ❌ Está prohibido usar contadores (`MAX_PDFS_PER_RUN > 1`).

---

### 2.2 Retorno inmediato

- ✅ Si se descarga 1 archivo → **retornar inmediatamente `"downloaded"`**.
- ❌ No continuar navegando.
- ❌ No seguir buscando otros archivos.

---

### 2.3 Caso sin resultados

- ✅ Si el crawler NO encuentra ningún archivo descargable:
  - Debe retornar **`"skipped"`**.
- ❌ Nunca debe quedarse en loops “por si acaso”.

---

### 2.4 Navegación por fuentes

- ✅ El crawler debe:
  - Probar una fuente
  - Si no funciona → pasar a la siguiente
- ❌ No insistir indefinidamente en una misma URL.

---

### 2.5 Persistencia

- ✅ El crawler **NO maneja lógica de persistencia compleja**.
- ✅ El crawler **confía en Round Robin** para:
  - recordar estado
  - rotar fuentes
  - volver a intentar luego

### 2.6 Procedencia de cada descarga

- Guardar bytes originales mediante `core.source_sidecar.save_download(data, dest, response.url)`.
- Usar la URL **final observada en la respuesta**, incluso si hubo redirección.
- Retornar `downloaded` solo si se guardaron el original y `<archivo>.source.json`.
- Un nombre de archivo existente se omite; nunca se sobrescribe para completar un sidecar.

---

## 3. PROHIBICIONES EXPLÍCITAS

Queda **EXPRESAMENTE PROHIBIDO**:

- ❌ `while True`
- ❌ loops largos sin salida temprana
- ❌ “bajar todo lo que haya”
- ❌ “ya que estoy, bajo varios”
- ❌ crawlers que dependen de velocidad
- ❌ crawlers que asumen sesiones largas
- ❌ crawlers que ignoran el retorno del Round Robin

Si un crawler hace cualquiera de estas cosas,
**viola el contrato**.

---

## 4. RESPONSABILIDAD DEL CRAWLER

El crawler:
- ❌ NO decide ritmo
- ❌ NO decide volumen
- ❌ NO decide cuándo “terminar”

El crawler:
- ✅ Ejecuta una acción mínima
- ✅ Retorna resultado
- ✅ Sale

---

## 5. RESPONSABILIDAD DEL ROUND ROBIN

El Round Robin:
- ✅ Decide orden
- ✅ Decide repetición
- ✅ Decide persistencia
- ✅ Decide cuándo detenerse

---

## 6. PLANTILLA OBLIGATORIA PARA TODO CRAWLER

Todo archivo crawler **DEBE** iniciar con este bloque:

```python
"""
CRAWLER CONTRACT — OBLIGATORIO

- Máximo 1 archivo por ejecución
- Retornar inmediatamente después de 1 descarga
- Si no descarga nada → retornar "skipped"
- No loops largos
- No contadores > 1
- Round Robin controla el ritmo
"""
