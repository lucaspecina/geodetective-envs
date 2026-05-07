- INTRO
    
    # GeoDetective Env: un entorno para entrenar agentes detectivescos de geolocalización
    
    ## La idea en una línea
    
    Construir un entorno de RL donde un agente recibe una fotografía —especialmente fotos antiguas— y tiene que descubrir dónde fue tomada investigando activamente con herramientas externas: mapas, satelital, Street View, archivos históricos, búsqueda web. El agente piensa, formula hipótesis, consulta tools, descarta, refina. Como Tom Davies en su serie *Geo Detective*, pero con un agente.
    
    ## Por qué fotos antiguas
    
    Las fotos modernas se resuelven cada vez más con lookup directo (reverse image search, matching contra Street View). Las fotos antiguas no: los edificios cambiaron o desaparecieron, las calles se reconfiguraron, los modelos VLM vieron pocas en pretraining, y hay que datar la foto en paralelo con ubicarla. Eso fuerza razonamiento genuino y es donde el problema deja de ser trivial. Es también un hueco real: todos los proyectos académicos actuales (GeoVista, GeoAgent, GeoRC, LocationAgent) trabajan con Street View moderno o Flickr contemporáneo. Foto histórica está casi vacío.
    
    ## Setup formal
    
    **Input**: una foto, idealmente histórica, posiblemente con metadata textual fragmentaria.
    
    **Target oculto**: coordenadas (lat, lon), idealmente más rango temporal.
    
    **Tools que el agente recibe**: static map por coordenadas/zoom/tipo, satelital, Street View por coordenadas/heading/pitch, geocoding directo e inverso, places search y nearby, elevation, web search, fetch URL, y un wrapper custom sobre archivos históricos. El agente descubre por sí mismo cómo combinarlas vía un loop ReAct estándar.
    
    **Reward**: continuo basado en distancia geodésica al ground truth, estilo GeoGuessr.
    
    ## De dónde sale cada pieza
    
    **Datos de entrenamiento y evaluación**. PastVu es la fuente principal: ~2 millones de fotos históricas geolocalizadas (1826-2000), con dump completo en Hugging Face (`nyuuzyou/pastvu`) en webdataset format y API pública. Smapshot complementa con 150.000 fotos georreferenciadas en 3D con pose completa (posición + ángulos + focal), API CC BY 4.0. Library of Congress aporta volumen adicional vía su API JSON pública. Para evaluación curada de máxima limpieza, postales antiguas físicas escaneadas. Como complemento, OldNYC, OldSF, SepiaTown, Historypin para ciudades específicas.
    
    **Filtrado anti-contaminación del corpus**. Antes de aceptar una foto al dataset se le corren tests adversarios: si reverse image search en Google Lens, Yandex o TinEye la resuelve, fuera. Si una descripción textual generada por VLM la encuentra googleando, fuera. Si VLMs grandes la ubican sin tools, fuera. Sobreviven solo fotos que ya demostraron resistir lookup y obligan a investigar.
    
    **APIs de geolocalización**. Google Maps Platform expone vía REST todo lo que se necesita: Static Maps, Street View Static, Places, Geocoding, Elevation, Photorealistic 3D Tiles, Map Tiles. Free tier de 200 USD mensuales en crédito. Como alternativa libre o complementaria: OpenStreetMap + Overpass para queries semánticas (búsquedas tipo "todos los molinos cerca de un río en esta zona"), Mapillary y KartaView para street view crowdsourceado, Sentinel-2 y NAIP para imágenes satelitales públicas, SRTM y MERIT para elevación.
    
    **Búsqueda web**. Tavily, Brave Search o Serper como tool de búsqueda; Jina Reader o Firecrawl para extraer contenido. Costos bajos, tier gratuito decente. Filtros aplicados en runtime para bloquear dominios de origen del dataset (pastvu.com, smapshot, etc.) y un hash perceptual para descartar resultados que contengan la imagen objetivo: cierra el shortcut de reverse image search disfrazado.
    
    **Infraestructura del agente**. GeoBenchX en GitHub provee el esqueleto: agente ReAct con LangGraph, 23 tools geoespaciales, evaluación con LLM as judge. Se clona, se reemplazan las tools por las relevantes para geodetective, y queda funcionando. OpenStreetMap MCP server de jagan-shanmugam aporta el patrón de exponer servicios geo como tools MCP. GeoVista da la receta de entrenamiento (SFT cold-start + RL con GRPO sobre trayectorias multi-turn) aunque su environment no se publicó. StreetLearn de DeepMind queda disponible si en algún momento se quiere navegación tipo panorama-a-panorama.
    
    **Stack de RL para la fase de entrenamiento**. Verifiers de Prime Intellect maneja loops multi-turn con tool calls y reward final, diseñado específicamente para esto. TRL de Hugging Face como alternativa más mainstream. Para prototipar antes de entrenar, smolagents o un loop ReAct propio en pocas líneas alcanza.
    
    ## Por qué esto vale la pena
    
    Tres cosas. Primera, el espacio de geolocalización con LLMs explotó en el último año pero está saturado en su variante moderna y vacío en histórica; entrar por foto antigua es un ángulo defendible. Segunda, GeoRC documentó que los VLMs aciertan ubicaciones pero alucinan razonamiento, lo que motiva trabajar el proceso investigativo, no el outcome. Tercera, no existe un entorno reusable empaquetado: GeoVista publicó modelo, no environment. Construir el environment como artefacto open source con foco histórico llena un hueco real y tiene público natural en la comunidad de RL environments tipo Prime Intellect Hub.
    
    ## Lo difícil de verdad
    
    Tres cosas que la infra no resuelve. Primera, el reward de outcome (acertar coordenadas) tiende a entrenar shortcuts en vez de investigación; mitigar requiere diseño adversarial del corpus y filtrado de tools, no solo distancia geodésica. Segunda, el costo computacional del RL multi-turn con tool calls es alto; un entrenamiento serio cuesta semanas y miles de dólares. Tercera, los términos de servicio de Google Maps tienen zonas grises para entrenamiento RL a escala; conviene mezclar con alternativas libres y leer los TOS en serio antes de publicar.
    
    ## Resumen ejecutivo
    
    Un environment de RL para entrenar y evaluar agentes geo-investigativos sobre fotos históricas, con PastVu y Smapshot como datasets primarios filtrados adversarialmente, Google Maps Platform y OSM como tools de exploración geo, Street View Static y Mapillary como tools visuales, búsqueda web filtrada como tool de archivo abierto, archivos históricos como tool especializada, y reward por distancia geodésica al ground truth, todo orquestado en un loop ReAct sobre LangGraph clonado de GeoBenchX y entrenado con Verifiers o TRL.
    
    ---
    
- otros proyectos que usen google maps, street view, etc para LLMs
    
    **Google Maps como tools para LLM, lo más cerca que existe.** El proyecto más concreto es **OpenStreetMap MCP server** de jagan-shanmugam (en GitHub, `open-streetmap-mcp`). Es un servidor MCP que expone OSM como tools listas para que un agente las llame: `geocode_address`, `reverse_geocode`, búsqueda de POIs, info de calles, navegación. Se enchufa a Claude Desktop o a cualquier cliente MCP en una línea de configuración. Es OSM, no Google Maps, pero el patrón arquitectónico es exactamente el que vos querés —servicios geo expuestos como tools tipadas— y para muchas tareas OSM alcanza o supera a Google. La pieza Google Maps específica como MCP server no la encontré pública en condiciones; hay implementaciones privadas y wrappers de un solo archivo en gists pero nada empaquetado. Si querés Google Maps, lo armás vos en una tarde envolviendo Static Maps, Street View Static, Places y Geocoding como funciones Python expuestas al agente. No es un proyecto, es código de pegamento.
    
    **Street View como entorno de RL ya empaquetado.** Existe **StreetLearn** de DeepMind, y es el único proyecto serio en este nicho. Empaqueta panoramas reales de Google Street View con grafo de conectividad para Londres, París y Nueva York, listo para entrenar agentes con RL. Open source, publicado para investigación. Su limitación es triple: cobertura solo de tres ciudades, snapshot vieja (2018-2019 aproximadamente), y la tarea para la que fue pensado es navegación —llegar de un punto a otro caminando— no geolocalización investigativa. Lo que te sirve es la **infraestructura de envoltura de Street View**: cómo exponer panoramas como observaciones, cómo manejar el grafo de adyacencias, cómo definir acciones de movimiento. Si no necesitás moverte panorama a panorama y te alcanza con consultar Street View Static API por coordenadas, StreetLearn es overkill y mejor te quedás con la API directa.
    
    **Agentes ReAct con tools geoespaciales ya construidos.** Acá hay dos proyectos a mirar. **GeoBenchX** (Solirinai/GeoBenchX en GitHub) tiene un agente ReAct construido con LangGraph y 23 tools geoespaciales reales: lectura de datos vectoriales y raster, operaciones espaciales, geocoding, visualización, evaluación con LLM as judge. La tarea para la que fue armado es análisis GIS clásico ("hacé un mapa de GDP per cápita por país"), no geolocalización investigativa, pero el **esqueleto del agente, el manejo del loop ReAct, el harness de evaluación y el patrón de tools tipadas** son directamente reutilizables. Lo clonás, sacás las tools que no te sirven, agregás Static Maps, Street View, Places y tu wrapper de archivos históricos, y tenés el agente funcionando. La familia **Autonomous GIS** de Penn State (LLM-Geo, LLM-Find, LLM-Cat de gladcolor) son agentes que ejecutan workflows GIS desde lenguaje natural, con buen manejo de generación y debugging de código. Heavyweight para tu caso, sirve más como inspiración conceptual que como base directa.
    
    **Modelos geo entrenados con RL y tools, lo más cerca conceptualmente.** **GeoVista** (Fudan + Tencent + Tsinghua, noviembre 2025) es el referente. Agente con loop ReAct (think → act → observe), tools de zoom de imagen y web search, entrenamiento con SFT cold-start + RL (GRPO) sobre trayectorias multi-turn, hierarchical reward geográfico. El modelo se publicó en Hugging Face. **No liberaron el environment como artefacto reusable**, pero la receta de entrenamiento está descrita en el paper con suficiente detalle para reproducirla. Un proyecto previo similar es **GeoAgent** de febrero 2026, con geo-similarity reward y un agente verificador de consistencia. Para Street View específicamente como tool de un agente, el paper "Evaluating Precise Geolocation Inference Capabilities of VLMs" (Pigeon, Stanford) construyó un agente que controla heading y pitch de Street View Static API a través de una tool simple, hace 5 iteraciones de "predicción → nueva consulta → refinamiento", y evalúa contra ground truth. Es un agente sencillo no entrenado, pero muestra el patrón mínimo de cómo se ve Street View como tool en un loop iterativo.
    
    **Implementaciones one-shot de geoguessr con LLMs.** Hay varios repos chicos en GitHub —`ccmdi/geobench`, bots de GeoGuessr, pruebas de Bellingcat— que envuelven Street View y le pasan la imagen a un LLM para que adivine. No son agentes ReAct serios, son scripts de una llamada, y no entrenan nada. Te sirven para entender el formato de input/output y como baselines de evaluación, no como infra reusable.
    
    **Lo que esto significa para vos en concreto.** Las dos piezas existentes que más te ahorran trabajo son **GeoBenchX como esqueleto del agente ReAct** (te da el loop completo y el harness de evaluación) y **OpenStreetMap MCP server como template del patrón tool-MCP** (lo extendés a Google Maps en horas). Street View como entorno completo navegable lo tenés en StreetLearn pero probablemente no lo necesitás —Street View Static API expuesta como tool simple `street_view(lat, lon, heading, pitch)` alcanza para todo el caso de uso de geodetective. La receta de entrenamiento RL la tomás de GeoVista. Lo único que vos construís genuinamente nuevo es el wrapper de archivos históricos como tool, el filtrado adversarial del dataset, y la integración de todas las piezas en un environment empaquetado y reusable.
    
    **Resumen crítico.** Hay piezas reusables fuertes para casi todo, pero **no hay un proyecto que combine Maps + Street View + web + archivo histórico como environment listo para entrenar agentes**. Eso es genuinamente lo que falta y es lo que harías. La buena noticia es que armarlo no es reinventar la rueda, es ensamblar componentes maduros y agregar la pieza de archivo histórico que es donde realmente está tu contribución.