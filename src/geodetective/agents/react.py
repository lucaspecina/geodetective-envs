"""ReAct agent multi-paso con tool calling vía OpenAI function calling format.

Tools disponibles inicialmente:
- web_search: buscar contexto histórico/geográfico (con filtros anti-shortcut).
- submit_answer: terminar y devolver respuesta estructurada.
"""
from __future__ import annotations
import os
import json
import base64
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field
from openai import OpenAI

from ..tools.web_search import web_search, TOOL_SCHEMA as WEB_SEARCH_SCHEMA


SUBMIT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": (
            "Submit tu respuesta final. Llamá esta función cuando tengas suficiente "
            "información para dar coordenadas. Si no podés precisar, devolvé la mejor "
            "estimación con confidence='baja'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "Descripción humana del lugar, ej: 'Plaza Mayor, Madrid, España'.",
                },
                "lat": {"type": "number", "description": "Latitud decimal."},
                "lon": {"type": "number", "description": "Longitud decimal."},
                "year": {
                    "type": "string",
                    "description": "Año estimado, single (ej '1965') o rango (ej '1960-1970').",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Resumen breve del razonamiento (qué pistas usaste).",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["alta", "media", "baja"],
                    "description": "Tu confianza en la respuesta.",
                },
            },
            "required": ["location", "lat", "lon", "reasoning", "confidence"],
        },
    },
}


SYSTEM_PROMPT = """Sos un detective geográfico investigativo. Recibís una fotografía histórica y tu tarea es descubrir DÓNDE fue tomada con la máxima precisión posible (coordenadas lat/lon) y CUÁNDO (año aproximado).

## Herramientas disponibles
1. `web_search(query, max_results)` — buscar contexto histórico, idiomas, arquitectura, edificios, vehículos, etc.
2. `submit_answer(...)` — devolver tu respuesta final.

## Estrategia recomendada
1. Examiná la foto cuidadosamente. Identificá TODAS las pistas posibles: arquitectura, vegetación, vehículos, ropa, idioma de carteles, modelos de objetos, iluminación, etc.
2. Formulá 2-3 hipótesis sobre dónde puede estar.
3. Hacé búsquedas web específicas para discriminar entre hipótesis. Ejemplos:
   - "edificios paneles soviéticos prefabricados Серебристый бульвар"
   - "Cyrillic street sign 1960s USSR architecture"
   - "Latin American colonial cathedral baroque Andean"
4. Refiná hipótesis con cada búsqueda. Pivotá si la evidencia contradice.
5. Cuando tengas confianza razonable (o ya hiciste suficiente sin progresar), llamá `submit_answer`.

## Reglas
- NO intentes "buscar la imagen en internet" — los dominios de archivos públicos están bloqueados de todos modos.
- Sé EFICIENTE con las búsquedas: cada query cuesta. Mejor 3-5 queries específicas que 10 vagas.
- Si después de varias búsquedas no podés precisar más, devolvé tu mejor estimación con confidence='baja'.
- Pensá en español. Las queries pueden estar en cualquier idioma apropiado."""


@dataclass
class ReActResult:
    """Resultado de una corrida del agente."""
    final_answer: Optional[dict] = None
    trace: list[dict] = field(default_factory=list)
    web_search_count: int = 0
    submit_called: bool = False
    steps_used: int = 0
    error: Optional[str] = None
    raw_messages: list[dict] = field(default_factory=list)


def run_react_agent(
    image_path: Path,
    model: str = "gpt-5.4",
    max_steps: int = 10,
    verbose: bool = True,
    user_prompt: str = "Investigá esta foto y devolvé las coordenadas (lat, lon) y año con submit_answer.",
) -> ReActResult:
    """Correr el agente ReAct con tool calling sobre una imagen.

    Args:
        image_path: ruta a la imagen.
        model: nombre del deployment en Foundry.
        max_steps: límite de iteraciones del loop.
        verbose: imprimir cada paso.

    Returns:
        ReActResult con la respuesta final y la trayectoria.
    """
    client = OpenAI(
        base_url=os.environ["AZURE_FOUNDRY_BASE_URL"],
        api_key=os.environ["AZURE_INFERENCE_CREDENTIAL"],
    )

    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    data_url = f"data:image/jpeg;base64,{img_b64}"

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    tools = [WEB_SEARCH_SCHEMA, SUBMIT_TOOL_SCHEMA]
    result = ReActResult()

    for step in range(max_steps):
        result.steps_used = step + 1
        if verbose:
            print(f"\n--- Step {step + 1}/{max_steps} ---")

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_completion_tokens=3000,
            )
        except Exception as e:
            result.error = f"API call failed at step {step+1}: {e}"
            if verbose:
                print(f"[ERROR] {e}")
            break

        msg = response.choices[0].message
        # Add assistant turn (puede tener content y/o tool_calls)
        assistant_turn: dict[str, Any] = {"role": "assistant"}
        if msg.content:
            assistant_turn["content"] = msg.content
            if verbose:
                print(f"[assistant] {msg.content[:300]}")
        if msg.tool_calls:
            assistant_turn["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        if msg.content is None and msg.tool_calls is None:
            # Edge case raro
            result.error = "Empty response (no content, no tool_calls)."
            break
        messages.append(assistant_turn)

        if not msg.tool_calls:
            # Modelo no llamó tool → terminó por su cuenta sin submit
            result.trace.append({"step": step + 1, "type": "final_text_no_submit", "content": msg.content})
            if verbose:
                print("[no tool call] modelo terminó sin submit_answer")
            break

        # Procesar cada tool call
        for tc in msg.tool_calls:
            fname = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            if verbose:
                args_preview = json.dumps(args, ensure_ascii=False)[:250]
                print(f"  ⚙ {fname}({args_preview})")

            if fname == "web_search":
                result.web_search_count += 1
                try:
                    sr = web_search(
                        query=args.get("query", ""),
                        max_results=int(args.get("max_results", 5)),
                    )
                    sr_dict = sr.to_dict()
                    if verbose:
                        print(f"     → {len(sr.results)} results (filtered {sr.blocked_count}/{sr.total_raw})")
                        for r in sr.results[:3]:
                            print(f"        · {r.url[:90]}")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(sr_dict, ensure_ascii=False)[:6000],
                        }
                    )
                    result.trace.append(
                        {"step": step + 1, "type": "web_search", "query": args.get("query"), "result_count": len(sr.results), "blocked": sr.blocked_count}
                    )
                except Exception as e:
                    err = f"web_search error: {e}"
                    if verbose:
                        print(f"     ✗ {err}")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": err})
                    result.trace.append({"step": step + 1, "type": "web_search_error", "error": str(e)})

            elif fname == "submit_answer":
                result.final_answer = args
                result.submit_called = True
                if verbose:
                    loc = args.get("location", "?")
                    lat, lon = args.get("lat"), args.get("lon")
                    conf = args.get("confidence", "?")
                    print(f"     → SUBMIT: {loc[:60]} ({lat}, {lon}) conf={conf}")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": "answer_submitted"})
                result.trace.append({"step": step + 1, "type": "submit", "answer": args})

            else:
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"Unknown tool: {fname}"})

        if result.submit_called:
            break

    result.raw_messages = messages
    return result
