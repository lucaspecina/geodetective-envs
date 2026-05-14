"""LLM adapter: rutea llamadas a OpenAI vs Anthropic vía Azure Foundry.

Foundry expone modelos OpenAI por `/openai/v1/chat/completions` (cliente openai)
y modelos Anthropic por `/anthropic/v1/messages` (formato nativo distinto).

Esta capa:
- MODEL_SPECS: registry con provider + capabilities por modelo.
- complete(model, messages, tools, ...): rutea por provider.
  - OpenAI path: passthrough al cliente openai (sin regresión vs código previo).
  - Anthropic path:
      1. Pre-procesa messages OpenAI-format → Anthropic format:
         * extrae system → parámetro top-level
         * fusiona consecutivos same-role en un solo content[] (strict alternation)
         * traduce role=tool → user con tool_result block
         * traduce image_url → image block con base64 source
         * traduce assistant.tool_calls → content blocks tool_use
      2. POST /anthropic/v1/messages via httpx.
      3. Parsea respuesta Anthropic → objeto OpenAI-shaped que react.py consume:
         response.choices[0].message.{content, tool_calls}
         con .tool_calls[i].id / .type / .function.name / .function.arguments.

Diseño post-Codex review (no startswith hack, registry-based, single-user-block fusion).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from openai import OpenAI


# === Model registry ===
# Provider, capabilities. Si un modelo no está en este dict, default openai/conservador.
MODEL_SPECS: dict[str, dict[str, Any]] = {
    # OpenAI line
    "gpt-5.4":     {"provider": "openai", "vision": True, "tools": True},
    "gpt-5.4-mini": {"provider": "openai", "vision": True, "tools": True},
    "gpt-5.4-nano": {"provider": "openai", "vision": True, "tools": True},
    "gpt-4o":      {"provider": "openai", "vision": True, "tools": True},
    "gpt-4o-mini": {"provider": "openai", "vision": True, "tools": True},
    "gpt-4.1":     {"provider": "openai", "vision": True, "tools": True},
    "gpt-4.1-mini": {"provider": "openai", "vision": True, "tools": True},
    # xAI (vía Foundry, formato OpenAI-compatible)
    "grok-4.3":                  {"provider": "openai", "vision": True, "tools": True},
    "grok-4-1-fast-reasoning":   {"provider": "openai", "vision": True, "tools": True},
    "grok-4-fast-reasoning":     {"provider": "openai", "vision": True, "tools": True},
    # Moonshot Kimi (vía Foundry, formato OpenAI-compatible)
    "Kimi-K2.5":   {"provider": "openai", "vision": True, "tools": True, "needs_thinking_budget": True},
    "Kimi-K2.6":   {"provider": "openai", "vision": True, "tools": True, "needs_thinking_budget": True},
    # DeepSeek text-only (documentado — visión rota silenciosa)
    "DeepSeek-V3.2": {"provider": "openai", "vision": False, "tools": True},
    "DeepSeek-V3.2-Speciale": {"provider": "openai", "vision": False, "tools": False},
    "DeepSeek-R1": {"provider": "openai", "vision": False, "tools": False},
    # Anthropic via Foundry (endpoint distinto)
    "claude-opus-4-6":   {"provider": "anthropic", "vision": True, "tools": True},
    "claude-opus-4-7":   {"provider": "anthropic", "vision": True, "tools": True},
    "claude-opus-4-5-20251101": {"provider": "anthropic", "vision": True, "tools": True},
    "claude-sonnet-4-6": {"provider": "anthropic", "vision": True, "tools": True},
    "claude-sonnet-4-5-20250929": {"provider": "anthropic", "vision": True, "tools": True},
    "claude-haiku-4-5-20251001": {"provider": "anthropic", "vision": True, "tools": True},
}


def get_provider(model: str) -> str:
    """Devuelve provider para un modelo. Default openai si no está registrado.

    Si un modelo claude-* no está explícito, asumimos anthropic por prefijo
    (fallback defensivo; el registry es la fuente canon).
    """
    spec = MODEL_SPECS.get(model)
    if spec:
        return spec["provider"]
    if model.lower().startswith("claude-"):
        return "anthropic"
    return "openai"


def get_spec(model: str) -> dict[str, Any]:
    """Devuelve specs del modelo. Si no está registrado, defaults conservadores."""
    return MODEL_SPECS.get(model, {"provider": get_provider(model), "vision": True, "tools": True})


# === OpenAI-shaped response objects (compat con react.py downstream) ===
# react.py accede a: response.choices[0].message.content / .tool_calls[i].id / .type
# / .function.name / .function.arguments  — todo via atributo (no dict).

@dataclass
class _FunctionCall:
    name: str
    arguments: str  # JSON string


@dataclass
class _ToolCall:
    id: str
    type: str = "function"
    function: Optional[_FunctionCall] = None


@dataclass
class _Message:
    content: Optional[str]
    tool_calls: Optional[list[_ToolCall]] = None
    # Extras para trace / debug. react.py no los lee — opcionales.
    thinking_blocks: list[str] = field(default_factory=list)
    raw_blocks: Optional[list[dict]] = None  # bloques crudos Anthropic
    finish_reason: Optional[str] = None


@dataclass
class _Choice:
    message: _Message
    finish_reason: Optional[str] = None


@dataclass
class AdapterResponse:
    """Shape compatible con `openai.ChatCompletion`.

    react.py espera response.choices[0].message.{content, tool_calls}.
    """
    choices: list[_Choice]
    raw: Optional[dict] = None  # respuesta cruda del provider
    provider: str = "unknown"


# === OpenAI passthrough ===
_openai_client: Optional[OpenAI] = None


def _get_openai_client(timeout: float = 180.0) -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(
            base_url=os.environ["AZURE_FOUNDRY_BASE_URL"],
            api_key=os.environ["AZURE_INFERENCE_CREDENTIAL"],
            timeout=timeout,
            max_retries=2,
        )
    return _openai_client


# === Anthropic translation ===

def _data_url_to_anthropic_image(url: str) -> dict:
    """`data:image/jpeg;base64,XXXX` → bloque Anthropic image."""
    if not url.startswith("data:"):
        # URL externa — Anthropic acepta también con source.type=url
        return {"type": "image", "source": {"type": "url", "url": url}}
    header, _, b64 = url.partition(",")
    media_type = "image/jpeg"
    if header.startswith("data:"):
        head_body = header[5:]
        if ";" in head_body:
            media_type = head_body.split(";")[0]
        elif head_body:
            media_type = head_body
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": b64},
    }


def _content_part_to_anthropic_block(part: dict) -> Optional[dict]:
    """Traduce un content part OpenAI → bloque Anthropic."""
    t = part.get("type")
    if t == "text":
        text = part.get("text", "")
        return {"type": "text", "text": text} if text else None
    if t == "image_url":
        url = part.get("image_url", {}).get("url", "")
        return _data_url_to_anthropic_image(url) if url else None
    # Ignoramos otros tipos
    return None


def _normalize_text_content(content: Any) -> list[dict]:
    """str → [{text}], list of parts → bloques traducidos."""
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        out: list[dict] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            block = _content_part_to_anthropic_block(part)
            if block:
                out.append(block)
        return out
    # Fallback: stringify
    return [{"type": "text", "text": str(content)}]


def to_anthropic_messages(messages: list[dict]) -> tuple[list[dict], Optional[str]]:
    """OpenAI messages → (Anthropic messages, system prompt).

    Reglas:
    - role=system → concat al system top-level (no mensaje).
    - role=user → bloques traducidos, acumulados con tool_results pendientes.
    - role=tool → bloque tool_result(tool_use_id, content), va al user pendiente.
    - role=assistant → bloques (text + tool_use traducidos).
    - Strict alternation: fusionamos consecutivos same-role en un mensaje.
    """
    system_parts: list[str] = []
    out: list[dict] = []
    pending_user: list[dict] = []
    pending_assistant: list[dict] = []

    def flush_user() -> None:
        if pending_user:
            out.append({"role": "user", "content": list(pending_user)})
            pending_user.clear()

    def flush_assistant() -> None:
        if pending_assistant:
            out.append({"role": "assistant", "content": list(pending_assistant)})
            pending_assistant.clear()

    for m in messages:
        role = m.get("role")
        content = m.get("content")

        if role == "system":
            # Concat solo texto (Anthropic system es string)
            blocks = _normalize_text_content(content)
            for b in blocks:
                if b.get("type") == "text":
                    system_parts.append(b["text"])
            continue

        if role == "user":
            # Antes de meter user, cerrar assistant pendiente
            flush_assistant()
            blocks = _normalize_text_content(content)
            pending_user.extend(blocks)
            continue

        if role == "tool":
            # Antes de empezar a acumular tool_results, cerrar el assistant pendiente.
            # Esto preserva el invariante: tool_result siempre va después de su tool_use.
            # (Codex review: sin esto, si el step termina con tools y sin user posterior,
            # el orden final flush queda invertido y Anthropic rechaza con 400.)
            flush_assistant()
            tool_use_id = m.get("tool_call_id") or m.get("id") or "unknown"
            tool_content = content
            if not isinstance(tool_content, str):
                try:
                    tool_content = json.dumps(tool_content, ensure_ascii=False)
                except (TypeError, ValueError):
                    tool_content = str(tool_content)
            pending_user.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": tool_content or "",
            })
            continue

        if role == "assistant":
            # Antes de meter assistant, cerrar user pendiente
            flush_user()
            blocks: list[dict] = []
            text = m.get("content")
            if isinstance(text, str) and text:
                blocks.append({"type": "text", "text": text})
            elif isinstance(text, list):
                blocks.extend(_normalize_text_content(text))
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") if isinstance(tc, dict) else None
                if fn is None:
                    continue
                try:
                    input_args = json.loads(fn.get("arguments", "{}") or "{}")
                except (json.JSONDecodeError, TypeError):
                    input_args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", "unknown"),
                    "name": fn.get("name", ""),
                    "input": input_args,
                })
            if blocks:
                pending_assistant.extend(blocks)
            continue

        # Roles desconocidos: ignorar pero log
        # (en práctica no debería pasar)

    # Orden final: assistant primero, user después. Si el último mensaje fue
    # un assistant con tool_use, pending_assistant tiene blocks y pending_user
    # está vacío. Si el último fue tool (post-fix), pending_assistant ya está
    # flusheado y pending_user tiene tool_results. En ambos casos este orden
    # mantiene strict alternation.
    flush_assistant()
    flush_user()
    system = "\n\n".join(system_parts).strip() if system_parts else None
    return out, system


def to_anthropic_tools(tools: Optional[list[dict]]) -> list[dict]:
    """OpenAI tools → Anthropic tools (strip function wrapper, parameters→input_schema)."""
    if not tools:
        return []
    out: list[dict] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        if "function" in t:
            fn = t["function"]
        else:
            fn = t
        if not isinstance(fn, dict):
            continue
        spec = {
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or fn.get("input_schema") or {"type": "object"},
        }
        out.append(spec)
    return out


def parse_anthropic_response(data: dict) -> AdapterResponse:
    """Anthropic response → AdapterResponse (OpenAI-shaped)."""
    content_blocks = data.get("content", []) or []
    text_parts: list[str] = []
    tool_calls: list[_ToolCall] = []
    thinking_parts: list[str] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        t = block.get("type")
        if t == "text":
            txt = block.get("text", "")
            if txt:
                text_parts.append(txt)
        elif t == "thinking":
            txt = block.get("text", "") or block.get("thinking", "")
            if txt:
                thinking_parts.append(txt)
        elif t == "tool_use":
            try:
                args_json = json.dumps(block.get("input", {}), ensure_ascii=False)
            except (TypeError, ValueError):
                args_json = "{}"
            tool_calls.append(_ToolCall(
                id=block.get("id", "unknown"),
                type="function",
                function=_FunctionCall(name=block.get("name", ""), arguments=args_json),
            ))
    content_str = "\n".join(text_parts) if text_parts else None
    msg = _Message(
        content=content_str,
        tool_calls=tool_calls if tool_calls else None,
        thinking_blocks=thinking_parts,
        raw_blocks=content_blocks,
        finish_reason=data.get("stop_reason"),
    )
    return AdapterResponse(
        choices=[_Choice(message=msg, finish_reason=data.get("stop_reason"))],
        raw=data,
        provider="anthropic",
    )


def _anthropic_base_url() -> str:
    base = os.environ["AZURE_FOUNDRY_BASE_URL"]
    return base.replace("/openai/v1", "/anthropic/v1")


def _anthropic_complete(
    model: str,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    max_tokens: int = 3000,
    timeout: float = 120.0,
    extra_body: Optional[dict] = None,
) -> AdapterResponse:
    """Call Anthropic Messages API vía httpx."""
    anth_messages, system = to_anthropic_messages(messages)
    anth_tools = to_anthropic_tools(tools)
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": anth_messages,
    }
    if system:
        body["system"] = system
    if anth_tools:
        body["tools"] = anth_tools
    if extra_body:
        body.update(extra_body)

    headers = {
        "Authorization": f"Bearer {os.environ['AZURE_INFERENCE_CREDENTIAL']}",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    url = f"{_anthropic_base_url()}/messages"
    r = httpx.post(url, headers=headers, json=body, timeout=timeout)
    if r.status_code != 200:
        # Levanta excepción con el cuerpo para diagnóstico
        raise RuntimeError(f"Anthropic API error {r.status_code}: {r.text[:600]}")
    return parse_anthropic_response(r.json())


# === Wrap OpenAI response to AdapterResponse-shape ===
# Para uniformidad. react.py ya sabe leer choices[0].message.content / tool_calls
# de los objetos openai nativos — pero envolvemos para que .raw / .provider / .thinking_blocks
# estén disponibles si downstream los quiere usar.

def _wrap_openai_response(resp) -> AdapterResponse:
    """Envuelve respuesta openai.ChatCompletion en AdapterResponse.

    react.py accede a campos via atributo. Mantenemos los objetos openai
    originales y solo agregamos metadata extra.
    """
    # NOTA: para minimizar regresión, devolvemos directamente el objeto openai
    # original y el llamador puede asumir esa interfaz. Si más adelante queremos
    # unificar, envolvemos aquí.
    return resp  # type: ignore[return-value]


# === Main entry ===

def complete(
    model: str,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    max_completion_tokens: int = 3000,
    tool_choice: str = "auto",
    timeout: float = 120.0,
    **extra,
) -> Any:
    """LLM completion uniforme; rutea por provider del modelo.

    Returns:
        Para OpenAI: objeto openai.ChatCompletion nativo (sin envolver).
        Para Anthropic: AdapterResponse con shape compatible.

    En ambos casos: response.choices[0].message.content / .tool_calls funcionan.
    """
    provider = get_provider(model)

    if provider == "openai":
        client = _get_openai_client()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens,
            "timeout": timeout,
            **extra,
        }
        # gpt-5.x rechaza tool_choice cuando tools no se pasa (400 Invalid value).
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        return client.chat.completions.create(**kwargs)

    if provider == "anthropic":
        # Anthropic no soporta tool_choice="auto" explícito (es default).
        # Si necesitamos forzar, pasamos tool_choice como dict {"type": "auto"|"tool"|"any"}.
        return _anthropic_complete(
            model=model,
            messages=messages,
            tools=tools,
            max_tokens=max_completion_tokens,
            timeout=timeout,
        )

    raise ValueError(f"unknown provider '{provider}' for model '{model}'")


def supports_vision(model: str) -> bool:
    return get_spec(model).get("vision", False)


def supports_tools(model: str) -> bool:
    return get_spec(model).get("tools", False)
