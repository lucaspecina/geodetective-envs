# OpenStreetMap MCP server (jagan-shanmugam) — Deep Dive

## Qué es

`open-streetmap-mcp` es un servidor MCP (Model Context Protocol) escrito en Python que expone OpenStreetMap como un conjunto de tools tipadas para que un LLM las invoque. No envuelve una sola API: combina **Nominatim** (geocoding y reverse geocoding), **Overpass API** (queries semánticas sobre POIs / tags OSM) y **OSRM** (routing por modo de transporte), y los empaqueta en 12 tools de "alto nivel" orientadas a casos de uso (encontrar escuelas, analizar barrio, sugerir punto de encuentro, etc.).

Está construido sobre `FastMCP` (la API decorativa del SDK oficial `mcp` de Anthropic / la fundación MCP), corre sobre transport **stdio**, y está pensado para enchufarse a clientes tipo Claude Desktop, Cursor, Windsurf, o el MCP Inspector. No incluye Pydantic explícito: los schemas se infieren de los type hints de Python (`float`, `List[Dict]`, etc.) más los docstrings, vía la introspección que hace FastMCP del decorador `@mcp.tool()`.

Para nuestro proyecto importa más como **patrón arquitectónico** que como artefacto a reusar tal cual: muestra una manera limpia y minimalista de ofrecer "servicios geo" como tools tipadas con un contexto compartido (sesión HTTP single-shot), que es exactamente lo que vamos a querer hacer con Google Maps Static / Street View / Places. Las herramientas Overpass que tiene son además genuinamente complementarias a Google Maps —Google no expone queries semánticas tipo "todos los molinos cerca de un río"— y eso es directamente relevante para un agente investigador histórico.

## Repo y artefactos

- **URL**: https://github.com/jagan-shanmugam/open-streetmap-mcp
- **License**: MIT
- **Lenguaje**: Python 100%
- **Métricas**: ~188 stars, 41 forks, 2 issues abiertos, 7 PRs (snapshot al momento del scrape)
- **Versión publicada**: `0.1.1` en PyPI (`uvx osm-mcp-server`)
- **Estructura del repo**:
  ```
  .
  ├── .github/workflows/
  ├── demo/                              (gifs de demo)
  ├── examples/
  │   ├── client.py                      (~100 LOC, demo simple)
  │   └── location_assistant_client.py   (~600 LOC, helper class para LLM)
  ├── src/osm_mcp_server/
  │   ├── __init__.py                    (8 líneas, expone main())
  │   └── server.py                      (~1600 líneas, todo el server)
  ├── pyproject.toml
  ├── uv.lock
  ├── LICENSE
  └── README.md
  ```

Todo el código vive en un único archivo: `src/osm_mcp_server/server.py`.

## Stack y arquitectura

- **SDK**: `mcp[cli]>=1.3.0` (SDK oficial de MCP). Concretamente usa la API `FastMCP` (`from mcp.server.fastmcp import FastMCP, Context`).
- **Transport**: **stdio** (no SSE ni HTTP). El entry point es `mcp.run()` invocado desde `osm_mcp_server/__init__.py:main()`.
- **HTTP client**: `aiohttp>=3.11.13`. Una `aiohttp.ClientSession` única se crea en el lifespan del server.
- **Python**: requiere `>=3.13`.
- **Build**: `hatchling` + `uv` para dependency management.
- **Sin Pydantic, sin JSONSchema explícito, sin tests**.

### Cómo se construye el server (patrón clave)

```python
# 1) Cliente HTTP wrapped en una clase con connect/disconnect async
class OSMClient:
    def __init__(self, base_url=...):
        self.session = None
        self.cache = {}  # declarado pero NUNCA usado
    async def connect(self): self.session = aiohttp.ClientSession()
    async def disconnect(self): await self.session.close()
    # ... métodos: geocode, reverse_geocode, get_route, get_nearby_pois, search_features_by_category

# 2) Application context que se inyecta en cada tool call
@dataclass
class AppContext:
    osm_client: OSMClient

# 3) Lifespan manager — abre/cierra la sesión HTTP del proceso
@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    osm_client = OSMClient()
    try:
        await osm_client.connect()
        yield AppContext(osm_client=osm_client)
    finally:
        await osm_client.disconnect()

# 4) Server con lifespan inyectado
mcp = FastMCP(
    "Location-Based App MCP Server",
    dependencies=["aiohttp", "geojson", "shapely", "haversine"],
    lifespan=app_lifespan,
)

# 5) Tools registradas vía decorator. La signature define el schema, el docstring va a la descripción.
@mcp.tool()
async def geocode_address(address: str, ctx: Context) -> List[Dict]:
    """..."""
    osm_client = ctx.request_context.lifespan_context.osm_client
    return await osm_client.geocode(address)
```

Notas:
- El **schema de cada tool se infiere de los type hints**. No hay `BaseModel`. `List[Dict]` → un array sin shape interna. Esto es elegante pero deja a discreción del LLM mucha estructura.
- `Context` se inyecta como argumento extra; `ctx.info(...)`, `ctx.warning(...)`, `ctx.report_progress(...)` mandan eventos al cliente MCP.
- El `OSMClient` se accede vía `ctx.request_context.lifespan_context.osm_client`. Pero —importante— **algunas tools no lo usan**: `find_schools_nearby`, `find_ev_charging_stations`, `analyze_neighborhood`, `find_parking_facilities` abren `aiohttp.ClientSession()` ad-hoc dentro de la tool en vez de reusar la sesión del lifespan. Inconsistencia/mal taste; ver más abajo.
- También hay dos `@mcp.resource(...)`: `location://place/{query}` (Nominatim search) y `location://map/{style}/{z}/{x}/{y}` (raster tiles). Estas también abren su propia `aiohttp.ClientSession()` cada vez.

## Tools implementadas

| Tool | Input (signature) | Output | Backend | Notas |
|---|---|---|---|---|
| `geocode_address` | `address: str` | `List[Dict]` (raw Nominatim + `coordinates` añadido) | Nominatim `/search?format=json&limit=5` | User-Agent hardcodeado `OSM-MCP-Server/1.0`. Cliente del lifespan. |
| `reverse_geocode` | `latitude: float, longitude: float` | `Dict` (raw Nominatim) | Nominatim `/reverse?format=json` | Cliente del lifespan. |
| `find_nearby_places` | `latitude, longitude, radius=1000m, categories=None, limit=20` | `Dict` agrupado por category→subcategory | Overpass API + bbox calculado a mano vía haversine | Categorías default: `amenity, shop, tourism, leisure`. |
| `get_route_directions` | `from_lat, from_lon, to_lat, to_lon, mode="car", steps=False, overview="simplified", annotations=False` | `{summary, directions, geometry, waypoints}` | OSRM público `router.project-osrm.org` (HTTP, no HTTPS) | Modos válidos: car/bike/foot. Si modo es inválido, warn y forzar a `car`. |
| `search_category` | `category, min_lat, min_lon, max_lat, max_lon, subcategories=None` | `{query, results, count}` | Overpass API (node/way/relation) | Acepta lista de subcategorías como filtro `or`. |
| `suggest_meeting_point` | `locations: List[Dict[str, float]], venue_type="cafe"` | `{center_point, suggested_venues, venue_type, total_options}` | Overpass | Calcula centro por **promedio simple** de lat/lon (no geo-sound). Expansión de radio si no hay matches. |
| `explore_area` | `latitude, longitude, radius=500` | `{address, categories: {cat: {sub: [features]}}, total_features}` | Overpass + reverse_geocode | Usa `ctx.report_progress(i, n)` para streaming. Itera 7 categorías. |
| `find_schools_nearby` | `latitude, longitude, radius=2000, education_levels=None` | `{schools: [...], count}` con distancia haversine | Overpass | Hardcodea filtros para amenity=school/university/kindergarten/college. **Abre su propia ClientSession**. |
| `analyze_commute` | `home_lat, home_lon, work_lat, work_lon, modes=["car","foot","bike"], depart_at=None` | `{home, work, commute_options, fastest_option, depart_at}` | OSRM + Nominatim | `depart_at` se acepta pero **no se usa** (no afecta el cálculo). |
| `find_ev_charging_stations` | `latitude, longitude, radius=5000, connector_types=None, min_power=None` | `{stations, count}` | Overpass `amenity=charging_station` | **ClientSession ad-hoc**. Parsea tags `socket:*` y `maxpower`. |
| `analyze_neighborhood` | `latitude, longitude, radius=1000` | `{location, scores: {overall, walkability, categories}, categories, ...}` | Overpass × 10 categorías | Score heurístico count+proximity (0–10). **ClientSession ad-hoc**. Sequencial, lento. |
| `find_parking_facilities` | `latitude, longitude, radius=1000, parking_type=None` | `{parking_facilities, count}` | Overpass `amenity=parking` | **ClientSession ad-hoc**. |

Resources MCP:
- `location://place/{query}` → JSON string desde Nominatim search.
- `location://map/{style}/{z}/{x}/{y}` → raster PNG tile. Soporta styles `standard` (OSM) y `cycle/transport/landscape/outdoor` de **Thunderforest** (que requeriría API key, pero acá no se pasa ninguna; los tiles van a fallar o devolver placeholder).

## Patrón de exposición tipada — claves para replicar

El "modelo arquitectónico" del repo es bien chico y vale la pena destilarlo abstracto:

1. **Un cliente async por backend externo, agrupado por dominio**. Acá `OSMClient` agrupa Nominatim+Overpass+OSRM porque conceptualmente todos son "OSM data". En Google Maps probablemente quieras `GoogleMapsClient` que multiplexa Geocoding/Places/Static/StreetView/Directions/Elevation, o uno por API si los rate limits y el billing son separados.
2. **Lifespan-managed shared state**. Una sola `aiohttp.ClientSession` (o `httpx.AsyncClient`) abierta al boot, cerrada al shutdown. Inyectada via `lifespan_context`. Esto evita el costo de TCP/TLS handshake por call y permite connection pooling.
3. **Tools como `@mcp.tool() async def name(args, ctx: Context) -> Output`**. Type hints + docstring son la fuente de verdad del schema. Un único decorador.
4. **Acceso al cliente via `ctx.request_context.lifespan_context.<field>`**. El `Context` es dependency injection.
5. **Tool de "primitiva" + tool de "caso de uso"**. El repo tiene tools básicas (`geocode_address`, `get_route_directions`) y tools compuestas (`analyze_neighborhood`, `analyze_commute`, `suggest_meeting_point`) que orquestan varias llamadas. Las primitivas son útiles para un agente que decide; las compuestas son atajos cómodos cuando un caso es recurrente. Para GeoDetective probablemente queramos **muchas primitivas** y dejar la composición al agente vía ReAct.
6. **Streaming opcional via `ctx.info`, `ctx.warning`, `ctx.report_progress`**. Útil cuando una tool es lenta (ej. `explore_area` itera 7 categorías).
7. **Output dicts JSON-serializable, sin clases ni Pydantic**. Llaves en snake_case. Sin schemas formales para outputs (es pena, complica al LLM si quiere parsear estructuras anidadas).

## Manejo de errores y rate limits

Pobre en ambos frentes. Nivel de detalle:

- **Errores HTTP**: cada método del cliente hace `if response.status == 200: ... else: raise Exception(f"Failed to ...: {response.status}")`. No tipos de excepción específicos, no body de error, no telemetría.
- **Timeouts**: ninguno. Ni en `aiohttp.ClientSession()` (default infinito), ni en cada call. Si Overpass se cuelga, el tool se cuelga.
- **Retries**: ninguno. Sin backoff, sin jitter. Si Nominatim devuelve 503 transitorio, falla.
- **Rate limiting**: ninguno. Esto es **especialmente preocupante** para Nominatim público, que tiene una política de **1 req/s y User-Agent identificable** ([usage policy](https://operations.osmfoundation.org/policies/nominatim/)). El server hardcodea el UA `OSM-MCP-Server/1.0` (correcto) pero no respeta el rate limit. Un agente que llame muchas veces puede ser baneado.
- **Cache**: hay un `self.cache = {}` declarado en `OSMClient.__init__` y **nunca leído ni escrito**. Código muerto.
- **Validaciones**: mínimas. `get_route_directions` valida que `mode in ["car","bike","foot"]`. `suggest_meeting_point` requiere ≥2 locations. Pero no valida bounding boxes (min<max), no valida latitud ∈ [-90,90], no valida bbox demasiado grande para Overpass.

Para nuestro proyecto, esto es un **anti-patrón claro**: vamos a querer retries+backoff (la API de Google falla con 429 frecuentemente bajo carga), timeouts agresivos por tool, y rate limiting client-side proactivo (especialmente para Street View Static, que cobra por cada request).

## Cómo se transfiere el patrón a Google Maps

El esqueleto (FastMCP + lifespan + un cliente async por dominio + decoradores `@mcp.tool()`) se transfiere uno-a-uno. Lo que cambia:

| Dimensión | OSM-MCP | Google Maps (lo que necesitamos) |
|---|---|---|
| Auth | Sin API key, User-Agent solamente | API key obligatoria por request (`?key=...`). Idealmente vía env var `GOOGLE_MAPS_API_KEY`, validada en lifespan startup. Posiblemente keys distintas por API si separamos billing. |
| Endpoints | Públicos: nominatim/overpass-api/router.project-osrm | Endpoints de Google: `maps.googleapis.com/maps/api/{geocode,place,staticmap,streetview,directions,elevation}/...` |
| Rate limits | Sin enforcement (debería ser 1 req/s a Nominatim) | QPS por API + cuota diaria + billing real. Necesitamos un `asyncio.Semaphore` por API y/o un token bucket. **Este es un cambio no-opcional**. |
| Costo | Cero | Real. Especialmente Street View Static y Places Details. Hay que loggear cada request con cost estimate, exponer un `usage_summary` tool, y considerar caching agresivo (ver abajo). |
| Cache | Declarado, no implementado | **Necesario**. Cachear por `(endpoint, params hash)` con TTL. Para un agente RL haciendo loops de ReAct, cachear hits puede ahorrar el 80%+ del costo. Persistente en disco, no in-memory. |
| Output binario | Tile resource devuelve `(bytes, mime)` | Street View Static y Static Maps devuelven JPEG/PNG. MCP soporta `ImageContent` en respuestas; FastMCP lo maneja si retornás bytes con mime. Verificar la versión del SDK. |
| Schemas | Type hints solos | Sugiero **Pydantic models** para outputs de tools que el agente va a parsear. Especialmente `places_search`, `streetview_metadata`, `directions`. Esto le da al LLM estructura y a nosotros validación. |
| Errores | `raise Exception(...)` genérico | Tipar: `QuotaExceededError`, `InvalidApiKeyError`, `NotFoundError`, `RateLimitError`. Retry con backoff solo en transitorios. |

Tools mínimas que querríamos exponer (mapeando 1:1 patrón del repo):

- `geocode_address` (Geocoding API) — paralelo a la del repo OSM, distinto backend.
- `reverse_geocode` (Geocoding API) — idem.
- `get_streetview_image` (Street View Static API) — input: `lat, lon, heading?, pitch?, fov?, size`; output: imagen.
- `get_streetview_metadata` (Street View Static API metadata endpoint) — input: `lat, lon, radius?`; output: si hay panorama disponible, fecha, panoid. **Esto es gratis y deberíamos llamarlo siempre antes del image** para no pagar por panoramas inexistentes.
- `get_static_map` (Maps Static API) — input: `center, zoom, size, markers?, path?`; output: imagen.
- `places_text_search`, `places_nearby_search`, `places_details` (Places API).
- `get_directions` (Directions API).
- `get_elevation` (Elevation API) — útil para validar hipótesis "esta foto fue tomada en una zona montañosa".

Tools de Overpass (OSM) que querríamos **además**: ver siguiente sección.

## ¿Tools de OSM también para nosotros?

**Sí, claramente sí.** Para un agente detective histórico, OSM ofrece cosas que Google Maps no:

1. **Overpass para queries semánticas**. Es la killer feature. Un agente puede preguntar "todas las iglesias construidas antes de 1900 en un bbox", "todos los molinos cerca de un río", "todas las estaciones de tren abandonadas en Argentina". Google Places no permite filtros tag-based libres así. Esto es enorme para razonar sobre fotos históricas porque las pistas suelen ser categóricas ("hay un faro", "se ve un viñedo"). Vale tener un tool tipo `overpass_query(bbox, tag_filters)` o más alto nivel `find_features_by_tags(bbox, tags={"historic":"castle"})`.
2. **Nominatim como geocoder secundario / fallback**. Es gratis (sin API key), y a veces resuelve nombres de lugares menos populares mejor que Google (lugares europeos pequeños, históricos). Costo: rate limit de 1 req/s.
3. **Datos OSM ricos para landmarks históricos**: `historic=*`, `building=church`, `man_made=lighthouse`, `tourism=museum`. Google Places tiene "type" pero la taxonomía OSM es mucho más fina para lo histórico.
4. **OSRM gratuito para distancias/tiempos**: si no necesitamos exactitud de Google, podemos usarlo para sanity-check rutas sin gastar quota.

Concretamente, propongo **dos servidores MCP separados** o **un solo server con dos clientes** (`google_client`, `osm_client`):
- `osm_*` tools: Nominatim + Overpass + (opcional) OSRM. Reusables del repo de jagan-shanmugam casi tal cual, con fixes de rate limit/timeouts.
- `google_*` tools: Static, Street View, Places, Directions, Elevation. Construidas desde cero replicando el patrón.

Tener ambos da al agente la opción de "primero localizo grueso con OSM gratis, después confirmo con Street View pago".

## ¿Es usable dentro de LangGraph?

**Crítico**: sí, pero con un wrapper. Detalles:

- El server expone tools vía protocolo MCP sobre stdio. **No tiene una API HTTP REST propia.** El cliente "habla MCP" (`mcp.ClientSession` + `stdio_client`).
- Los ejemplos `examples/client.py` y `examples/location_assistant_client.py` muestran el patrón: spawneás el proceso del server vía `StdioServerParameters(command="osm-mcp-server", ...)`, abrís un `ClientSession`, y llamás `await session.call_tool("geocode_address", {"address": "..."})`. Las respuestas vienen como `result.content` (lista de `TextContent` con JSON serializado en `.text`).
- Para **LangGraph**, hay dos caminos limpios:
  1. **`langchain-mcp-adapters`** (paquete oficial de LangChain): convierte tools MCP en `BaseTool` de LangChain, listas para ser nodos `ToolNode` en LangGraph. Es el camino recomendado si querés mantener el aislamiento de proceso.
  2. **Importar directo en proceso**: dado que es Python, no hace falta MCP en absoluto si todo corre en el mismo proceso. Podríamos importar las funciones (los `OSMClient` methods, no los `@mcp.tool` wrappers) y exponerlas como tools de LangChain con `@tool` o con `StructuredTool.from_function`. Esto es más rápido (no hay fork+stdio), pero pierde la portabilidad MCP (no podés usar el mismo server desde Claude Desktop).

**Recomendación**: para el environment de RL en LangGraph, **importar las funciones core en proceso** (refactorizar para que los `OSMClient` y `GoogleMapsClient` sean librerías reutilizables, y los `@mcp.tool` sean solo el adapter MCP). Mantener el server MCP como fachada externa para casos donde queramos exponer las mismas tools a un cliente humano (Claude Desktop, etc.). Esto es exactamente la separación lib/adapter que conviene.

Lo que **no** podemos hacer del repo tal cual: usarlo como dependencia importable. Está diseñado como CLI (`osm-mcp-server`), no como librería. El código vive todo en `server.py` con los `@mcp.tool` decorators encima de funciones que dependen de `Context`. Para reusar tendríamos que refactorizar.

## Cosas que reusamos directo

Pocas en realidad, porque el repo no está pensado como librería. Lo que sí podemos copy/adapt sin pensar:

- **El patrón `OSMClient` con `connect/disconnect` async + lifespan**. Lo replicamos para `GoogleMapsClient`.
- **El cálculo de bbox a partir de lat/lon/radius (vía aproximación 1° ≈ 111 km)**. Repetido a lo largo del archivo. Es estándar; no necesitamos copiarlo, pero el snippet sirve de referencia.
- **El `haversine` distancia entre dos puntos**. Repetido literalmente 3 veces en el archivo (lines ~908, ~1179, ~1554). Lo deberíamos tener como utility.
- **El template de query Overpass para buscar features por tag-key/value en bbox**. Util si construimos un tool genérico `overpass_query`.
- **El `User-Agent` correcto y respetuoso para Nominatim** (necesario para no ser baneados; deberíamos poner uno propio identificable: `GeoDetective-Envs/0.1 (+contacto)`).

## Cosas que adaptamos

- **El esqueleto del server con `FastMCP + lifespan + Context`**. Replicamos el shape, ajustando para que el lifespan inicialice también un `GoogleMapsClient` con la API key cargada de env.
- **Tool primitives**: las firmas de `geocode_address` y `reverse_geocode` se mantienen casi idénticas; sólo cambia el backend.
- **Naming**: snake_case, docstrings ricos, type hints. Buenos hábitos del repo, los mantenemos.
- **Outputs como dicts JSON-serializable**, pero **con Pydantic models** para forzar shape (mejora vs. el repo).
- **Streaming via `ctx.report_progress`** para tools lentas (ej. una búsqueda iterativa de Street View). El repo tiene este pattern y es valioso.
- **Tools compuestas como atajos opcionales**, pero priorizando primitivas. El repo se va a la pileta con tools como `analyze_neighborhood` que orquestan 10 queries Overpass; nosotros queremos que el agente decida cuándo orquestar.

## Cosas que NO copiamos

- **Sin retries / sin backoff / sin timeouts**. Inaceptable. Necesitamos `tenacity` o equivalente, con timeouts por tool.
- **Sin rate limiting**. Hay que respetar Nominatim 1 req/s, y para Google evitar 429s. Token bucket / semáforo.
- **El `self.cache = {}` muerto**. O implementás cache, o no lo declares. Vamos a implementarlo.
- **`aiohttp.ClientSession()` ad-hoc dentro de tools** (`find_schools_nearby`, `find_ev_charging_stations`, `analyze_neighborhood`, `find_parking_facilities`, las dos resources). Inconsistente con el lifespan client. Deberíamos usar **siempre** la sesión del lifespan.
- **Función `haversine` redefinida 3 veces inline dentro de funciones**. Antipatrón obvio.
- **`depart_at` aceptado pero ignorado** en `analyze_commute`. Si un parámetro no se usa, no lo expongas — confunde al LLM.
- **OSRM via HTTP plano** (`http://router.project-osrm.org/...`, no HTTPS). Mal por privacidad y porque algunos entornos bloquean HTTP no cifrado.
- **OSRM público** como dependencia productiva: el demo server tiene rate limits no documentados y puede caerse. Para producción habría que hostear OSRM propio o usar otro provider.
- **Thunderforest tiles sin API key**: las styles `cycle/transport/landscape/outdoor` no van a funcionar (Thunderforest requiere key). Es un bug.
- **Tools "compuestas" demasiado opinionadas** (`analyze_neighborhood` con su scoring 0–10 hardcodeado). Si replicáramos algo así, el scoring debería ser configurable o salir afuera del server.
- **Errors como `raise Exception(...)`** genéricas con string interpolada. Tipar.
- **Cero tests**. Para un environment de RL queremos al menos smoke tests + mocks de las APIs externas.
- **`requires-python = ">=3.13"`** es agresivo y nos limita. Probablemente queramos `>=3.11`.

## Decisión: apalancar / mirar / descartar

**Mirar (estudiar y replicar el patrón) — no apalancar como dependencia.**

Justificación:

- El **patrón arquitectónico (FastMCP + lifespan + AppContext + tools decoradas)** es exactamente lo que queremos para nuestras tools. Lo replicamos.
- El **código en sí no es reusable como librería**: todo vive en un único `server.py` de 1600 líneas con la lógica entrelazada con los decoradores MCP. Para extraerlo tendríamos que refactorizar más de lo que vale.
- La **calidad del código tiene varios anti-patterns** (sin retries, sin timeouts, sesiones HTTP redundantes, función `haversine` duplicada, cache muerto, parámetros ignorados, errors genéricas, cero tests). No es un baseline al que queramos atarnos.
- Las **funcionalidades de OSM (Nominatim + Overpass + OSRM) sí son valiosas** para nuestro agente —especialmente Overpass para queries semánticas tipo "todos los molinos cerca de un río"— pero las vamos a re-implementar limpias en nuestra propia capa, no a depender del paquete `osm-mcp-server`.
- Si en algún momento queremos exponer nuestras tools a Claude Desktop u otro cliente MCP, el patrón de este repo es la receta a seguir.

Plan concreto sugerido, en orden:

1. Diseñar `GoogleMapsClient` (async, lifespan-managed, una key por env, retries+timeout+rate-limit, caché en disco).
2. Diseñar `OSMClient` propio (Nominatim + Overpass), respetando rate limit de Nominatim, con tool genérico `overpass_query` además de tools alto-nivel.
3. Capa de tools tipadas con Pydantic models para inputs y outputs, expuestas como funciones puras Python (no `@mcp.tool`).
4. Adapter LangGraph que envuelva esas funciones como `StructuredTool` para el agente del environment.
5. (Opcional, después) Adapter MCP que envuelva las mismas funciones con `@mcp.tool()` en estilo `osm-mcp-server` para exposición externa.

Referencias de archivos del repo investigado (paths absolutos descargados localmente para revisión):

- `/tmp/osm_mcp/server.py__src_osm_mcp_server_server.py` — server completo (~1600 LOC).
- `/tmp/osm_mcp/__init__.py__src_osm_mcp_server___init__.py` — entry point.
- `/tmp/osm_mcp/pyproject.toml__pyproject.toml` — deps mínimas (`aiohttp`, `mcp[cli]`, Python 3.13+).
- `/tmp/osm_mcp/client.py__examples_client.py` — cómo conectar como cliente MCP stdio.
- `/tmp/osm_mcp/location_assistant_client.py__examples_location_assistant_client.py` — wrapper class para LLM/agent.
- `/tmp/osm_mcp/README.md__README.md` — config Claude Desktop, instalación.
