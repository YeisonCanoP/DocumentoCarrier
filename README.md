# La Verdad del Documento del Carrier

Extrae **cliente, carrier, cobertura y prima** de ilustraciones de carriers,
demuestra de dónde salió cada dato, y **se niega a presentar como verificado**
lo que el documento no respalda.

> **Principio del sistema:** la fuente de verdad para dinero y cobertura es el
> documento del carrier — nunca el valor solicitado ni el que muestra una
> interfaz. Y **coincidir no es verificar**: si la fuente no es válida, dos
> números iguales siguen sin estar verificados.

Reto de Ingeniería PBG. Todos los datos son sintéticos.

---

## Arrancar

```bash
docker compose up --build
```

Abrir **http://localhost:8000** · API interactiva en **/docs**

Los 108 tests dentro del contenedor:

```bash
docker compose run --rm tests
```

Sin Docker:

```bash
uv sync
uv run uvicorn carrier_truth.adapters.inbound.http.app:app --reload
uv run pytest
uv run carrier-truth          # los veredictos en la terminal
uv run carrier-truth C006     # un caso concreto
```

---

## Qué hace, con los datos reales del paquete

El dataset no es una muestra homogénea: son seis trampas distintas. Esta tabla es
el resumen de lo que el sistema detecta.

| Caso | Solicitado | Documento dice | Veredicto |
|---|---|---|---|
| **C001** Ana Rivera | cobertura 450.000 | Face Amount **$50.00** | Cobertura **implausible**: por debajo del mínimo razonable y a un factor de 0,0001 de lo solicitado. La prima coincide, pero baja a *verificado con reserva* porque el documento que la respalda tiene una cifra corrupta. |
| **C002** Marco Diaz | 250.000 / 47,50 | idéntico | **Verificado**, 4 de 4 campos. |
| **C003** Juan Perez | 100.000 / 60 | Applicant **"Client"**, prima **$720.00 ANNUAL** | Cliente **sin identidad**: "Client" es plantilla, no identifica a nadie. La prima se verifica tras normalizar (720 ÷ 12 = 60), declarando que la cifra mensual es un cálculo nuestro. |
| **C004** Sara Lopez | 500.000 / 89 | idéntico | **Verificado**, 4 de 4 campos. |
| **C005** David Cruz | 200.000 / 58 | prima 58, **+ rider 73** | Se toma la etiquetada `Premium` como prima contractual y **se declara** el rider como alternativa no contratada. |
| **C006** Elena Torres | 300.000 / 66 | **todo coincide**, pero el PDF dice *"Portal Print View… NOT an issued illustration"* | **Nada se verifica.** El documento no es una ilustración emitida, así que no hay fuente contra la cual verificar — aunque los números coincidan. |

**C006 es el caso que importa.** Todos sus valores coinciden con la solicitud y
con la UI. Un sistema que solo compara valores lo marca verde, y estaría
presentando como verificada una captura de pantalla del portal.

---

## Cómo se demuestra la procedencia

Cada dato viaja con la línea literal del documento y el offset exacto del
fragmento que se extrajo:

```json
{
  "field": "cobertura",
  "value": "$50.00",
  "requested": "$450,000.00",
  "status": "unverified_implausible",
  "verified": false,
  "next_action": "Solicitar de nuevo el documento: la cifra no puede ser real.",
  "evidence": {
    "document": "C001.pdf",
    "page": 1,
    "line": 4,
    "char_span": [14, 19],
    "snippet": "Face Amount: $50.00",
    "matched_text": "50.00",
    "rule_id": "face_amount_v1",
    "locator": "C001.pdf · pág. 1 · línea 4 · car. 14-19"
  },
  "reasons": [
    { "code": "implausible_amount",
      "message": "$50.00 es implausible como face amount: está por debajo del mínimo razonable de $10,000.00…" },
    { "code": "implausible_amount",
      "message": "El documento indica $50.00 frente a $450,000.00 solicitados: un factor de 0.0001…" }
  ]
}
```

Dos propiedades que son invariantes verificadas por tests, no promesas:

1. **No existe forma de obtener un valor sin su evidencia.** En `field_rules.py`
   toda regla devuelve valor + `Evidence` juntos: la trazabilidad es el tipo de
   retorno, no una convención que se pueda olvidar.
2. **El `char_span` apunta de verdad al fragmento** dentro de la línea citada
   (`snippet[a:b] == matched_text`), así que se puede resaltar sin reabrir el PDF.

---

## Arquitectura

Hexagonal (puertos y adaptadores). El dominio no importa FastAPI, ni pypdf, ni
el filesystem.

```
src/carrier_truth/
  domain/                      núcleo puro — cero IO
    model.py                   Money, Premium, Cadence, Evidence, FieldVerdict, CaseReport
    ports.py                   Protocols: DocumentTextExtractor, QuoteRequestRepository,
                               CarrierDocumentRepository
    services/
      authority_policy.py      ¿es este documento una fuente de verdad?
      field_rules.py           texto+coordenadas → candidatos con procedencia
      reconciliation.py        el motor de veredictos
  application/use_cases.py     orquestan puertos, sin criterio propio
  adapters/
    inbound/http/              FastAPI: routers, DTOs, mapper dominio→presentación
    inbound/cli.py             el mismo núcleo sin HTTP
    outbound/                  pypdf_extractor, filesystem
  composition.py               wiring explícito
```

Tres cosas que esto compra, y que son la razón de elegirlo en un reto de una hora:

- **El criterio se lee en dos minutos.** Toda la lógica de por qué el sistema se
  niega a verificar algo está en `reconciliation.py` y `authority_policy.py`, sin
  HTTP ni parseo de PDF alrededor.
- **El dominio se testea sin PDFs ni servidor.** `tests/unit/test_reconciliation.py`
  construye documentos a mano. Los 108 tests corren en 0,27 s, que es lo que
  permite tenerlos dentro del presupuesto de tiempo.
- **Cambiar la extracción es un adaptador nuevo.** Cuando haga falta OCR o un
  LLM para absorber cientos de layouts, se implementa el mismo puerto y el motor
  no se toca.

---

## Respuestas escritas

### ¿Qué se extrae y de dónde viene cada dato?

Cuatro campos: cliente (`Applicant`), carrier, cobertura (`Face Amount`) y prima
(`Premium`). Cada uno lleva documento, página, línea, offset de caracteres, la
línea literal y el `rule_id` de la regla versionada que lo extrajo.

**No se usa OCR ni LLM.** Los PDFs del paquete son texto real, así que la
extracción es determinista con expresiones regulares. La razón es la
auditabilidad: el reto pide demostrar la procedencia, y una regex versionada con
coordenadas es una prueba reproducible; *"el modelo lo leyó así"* no lo es.
Además el mismo PDF produce siempre el mismo veredicto, que es requisito para
que los tests dorados signifiquen algo. La ruta con LLM está prevista como otro
adaptador del puerto `DocumentTextExtractor`, no como el camino base.

### ¿Cómo se detecta una contradicción importante y qué se hace?

El estado de un campo es un enum de **ocho** valores, no un booleano, porque "no
verificado" tiene causas que exigen acciones humanas distintas:

| estado | qué pasó | siguiente paso |
|---|---|---|
| `verified` | coincide, fuente válida | ninguna |
| `verified_with_caveat` | coincide, pero hay algo que declarar | leer la reserva antes de citar la cifra |
| `unverified_conflict` | documento y solicitud difieren | resolver con el carrier |
| `unverified_implausible` | la cifra no puede ser real | pedir el documento de nuevo |
| `unverified_ambiguous` | el documento ofrece varias respuestas | confirmar cuál aplica |
| `unverified_no_identity` | el documento no dice a quién pertenece | pedir ilustración nominativa |
| `unverified_untrusted_source` | la fuente no es autoridad | pedir la ilustración emitida |
| `unverified_missing` | el campo no está | pedir documento completo |

Solo dos de los ocho permiten presentar el dato como verificado. La propiedad
`is_presentable_as_verified` vive en el dominio, no en la UI, para que ningún
cliente pueda decidir por su cuenta pintar de verde un conflicto.

Cuando el sistema se niega, **siempre dice por qué y qué hace falta** — es una
invariante con test (`test_todo_campo_no_verificado_explica_por_que`).

### El gate de autoridad: por qué es un veto y no un puntaje

`assess_authority()` corre **antes** de cualquier comparación de valores y puede
invalidar el caso entero. Es una lista de vetos (`NOT an issued illustration`,
`portal print view|preview`, `specimen|draft`, `for illustrative purposes only`),
no un puntaje ponderado: un puntaje permitiría que "muchos números correctos"
compensen "la fuente es una captura de pantalla", que es justo lo que no debe
pasar.

Dos decisiones dentro:

- **`UNKNOWN` se trata como falta de autoridad.** Sin veto pero sin encabezado de
  ilustración emitida, no se presume autoridad. Un "no sé" sobre la fuente es,
  operativamente, una falta de fuente.
- **El veto alcanza a los cuatro campos**, no solo a dinero y cobertura. Si el
  documento no lo emitió el carrier, tampoco sirve para afirmar la identidad del
  cliente.

Al aplicar el veto **se conservan el valor y la evidencia**. Ocultarlos no
ayudaría a nadie; lo que cambia es la afirmación, que pasa de *"esto es así"* a
*"esto es lo que dice un documento en el que no nos podemos apoyar"*.

### La prima no es un número, es un monto más una periodicidad

`Premium = (Money, Cadence)`. Separarlos es exactamente el error que C003 pone a
prueba: `$720.00 ANNUAL` y `$60.00 MONTHLY` son el mismo precio, y comparar
`720 != 60` reporta un conflicto falso.

Cuando se normaliza, el campo queda `verified_with_caveat` y el caveat dice sin
rodeos: *"el documento no dice $60.00 mensual, dice $720.00 anual; la cifra
mensual es un cálculo nuestro"*. Presentar el resultado del cálculo como si fuera
una cita del documento sería la misma clase de error que el reto castiga.

Los montos son `Decimal`, nunca `float`.

### Integridad transversal: una decisión más allá del enunciado

Si un documento contiene **un** monto implausible, los demás campos monetarios de
**ese mismo documento** bajan de `verified` a `verified_with_caveat`.

En C001 la prima ($62) coincide perfectamente con la UI y la tentación es marcarla
verde. Pero el face amount del mismo PDF es $50.00: algo salió mal al generar o
al leer ese documento. Si una cifra llegó corrupta, no hay base para afirmar que
las otras llegaron bien. Es una degradación suave — se sigue reportando el
valor — que deja el rastro para la persona que decide.

### Validaciones

El criterio es que **el dominio se protege solo y HTTP traduce**: un
`QuoteRequest` que existe es un `QuoteRequest` comparable, validado en
`__post_init__` y no en el router. Así el motor no tiene que defenderse de basura
y no hay forma de colar datos inválidos saltándose la capa HTTP.

El hallazgo que justifica ponerlo ahí:

```python
Decimal("NaN")                                           # se construye sin error
abs(Decimal("NaN") - Decimal("50")) > Decimal("0.01")    # False  ← el peligro
```

Un NaN **no falla**: pasa silenciosamente la comparación de tolerancia del motor
y sale reportado como *«coincide»*. Es precisamente el error que este reto
castiga, y habría entrado por un campo de formulario. Se rechaza en la frontera
del dominio junto con infinitos, negativos, ceros, topes de sanidad y `float`.

| capa | valida |
|---|---|
| `QuoteRequest.__post_init__` | NaN, ∞, ≤ 0, topes, `float`, nombre vacío o > 200 |
| `PyPdfTextExtractor` | firma `%PDF-`, vacío, cifrado, 0 páginas, > 50 páginas, fallo por página |
| `api.py` | forma de `case_id`, tamaño de subida, dinero con formato humano (`$450,000.00`), saneado del nombre de archivo |
| repositorio de documentos | contención de ruta (`is_relative_to`) |

### ¿Qué quedó fuera, y por qué?

- **OCR y extracción con LLM** — innecesarios con PDFs de texto y no auditables
  en la capa que el reto pide demostrar. Previstos como adaptadores.
- **Resaltado sobre la página renderizada del PDF** — exigiría `poppler` en la
  imagen y ~20 minutos más. Página + línea + offset ya es procedencia
  verificable; el riesgo de no cerrar en la hora superaba la ganancia.
- **Autenticación, persistencia y multi-tenant** — fuera del alcance de la
  demostración.
- **Layouts de carriers no vistos** — el sistema reconoce el formato del paquete.
  Se extiende añadiendo reglas en `field_rules.py`, y hasta entonces un documento
  no reconocido cae en `UNKNOWN`, que se trata como falta de autoridad: falla
  cerrado, no abierto.

---

## API

| endpoint | qué devuelve |
|---|---|
| `GET /api/cases` | los 6 casos verificados, con procedencia completa |
| `GET /api/cases/{case_id}` | un caso |
| `POST /api/verify` | verifica un PDF arbitrario contra los valores que se le indiquen |
| `GET /api/rules` | **las reglas, umbrales y estados que aplica el motor** |
| `GET /api/health` | sonda de vida, reporta si encontró el paquete de datos |

`GET /api/rules` merece una nota: si el sistema exige demostrar de dónde vino
cada dato, tiene que poder demostrar con qué criterio lo juzgó. Se construye
leyendo los objetos del código real, no de una lista escrita a mano que se
desincroniza y acaba mintiendo.

`POST /api/verify` existe para demostrar que el motor no está afinado a los 6
casos de prueba.

---

## Tests

```
108 tests · 0,27 s
```

- `tests/unit/test_reconciliation.py` — el dominio, construyendo documentos a
  mano: sin PDFs, sin disco, sin servidor.
- `tests/unit/test_validaciones.py` — invariantes del dominio, rechazos del
  extractor, frontera HTTP.
- `tests/golden/test_golden_cases.py` — los 6 casos reales congelados.

Se congela el estado de cada campo, el outcome y la procedencia. **No** se
congela el texto de las razones: bloquear la redacción con tests hace que nadie
la mejore.

---

## Reto universal de screen sharing

Respuesta en **[RESEARCH_SCREEN_SHARING.md](RESEARCH_SCREEN_SHARING.md)**.
