"""Smoke test: para cada modelo deployado en Foundry, verifica 3 capacidades:
- Text chat: "reply ok"
- Vision: cuadrado rojo + "what color is this?" — el check que faltó al pillar DeepSeek-V3.2
- Tool calling: función dummy "get_weather"

Uso:
    python scripts/test_models_smoke.py                       # set por defecto
    python scripts/test_models_smoke.py gpt-5.4 Kimi-K2.6     # modelos específicos
    MODELS="gpt-5.4,grok-4.3" python scripts/test_models_smoke.py

Output: tabla por stdout + experiments/E008_multimodel/smoke_test_results.json
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path

# Forzar UTF-8 en stdout para Windows cp1252
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import httpx
from openai import OpenAI
from PIL import Image

# Cargar .env
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

DEFAULT_MODELS = [
    # Top tier
    "gpt-5.4",
    "claude-opus-4-6",
    "grok-4.3",
    "Kimi-K2.6",
    # Mid tier
    "gpt-5.4-mini",
    "claude-sonnet-4-6",
    "grok-4-1-fast-reasoning",
    "Kimi-K2.5",
    # Reference de generación previa OpenAI
    "gpt-4o",
]

# Token budget: subido a 500 porque modelos con thinking mode (Kimi, reasoning grok)
# consumen ~30 tokens antes de output visible.
MAX_TOKENS_TEXT = 500
MAX_TOKENS_VISION = 500
MAX_TOKENS_TOOLS = 500


def make_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ["AZURE_FOUNDRY_BASE_URL"],
        api_key=os.environ["AZURE_INFERENCE_CREDENTIAL"],
        timeout=45.0,
    )


def is_claude(model: str) -> bool:
    """Claude usa endpoint Anthropic-nativo, no OpenAI Chat Completions."""
    return model.lower().startswith("claude-")


def anthropic_base_url() -> str:
    """Foundry expone Anthropic en /anthropic/v1, mismo host que /openai/v1."""
    return os.environ["AZURE_FOUNDRY_BASE_URL"].replace("/openai/v1", "/anthropic/v1")


def anthropic_post(path: str, body: dict, timeout: float = 45.0) -> httpx.Response:
    return httpx.post(
        f"{anthropic_base_url()}{path}",
        headers={
            "Authorization": f"Bearer {os.environ['AZURE_INFERENCE_CREDENTIAL']}",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=timeout,
    )


def make_red_square_b64(size: int = 64) -> str:
    img = Image.new("RGB", (size, size), (220, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_text(client: OpenAI, model: str) -> tuple[bool, str]:
    if is_claude(model):
        try:
            r = anthropic_post(
                "/messages",
                {
                    "model": model,
                    "max_tokens": 500,
                    "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
                },
            )
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}: {r.text[:140]}"
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            content = text.strip().lower()[:40]
            return "ok" in content, content or "(empty)"
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)[:140]}"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            max_completion_tokens=500,
        )
        content = (resp.choices[0].message.content or "").strip().lower()[:40]
        ok = "ok" in content
        return ok, content or "(empty)"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:140]}"


def test_vision(client: OpenAI, model: str) -> tuple[bool, str]:
    b64 = make_red_square_b64()
    if is_claude(model):
        try:
            r = anthropic_post(
                "/messages",
                {
                    "model": model,
                    "max_tokens": 500,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "What color is the square? Reply with one word: red, blue, or green.",
                                },
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": b64,
                                    },
                                },
                            ],
                        }
                    ],
                },
            )
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}: {r.text[:140]}"
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            content = text.strip().lower()[:60]
            return "red" in content, content or "(empty)"
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)[:140]}"

    data_url = f"data:image/png;base64,{b64}"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Look at the image. What color is the square? "
                                "Reply with one word: red, blue, or green."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            max_completion_tokens=500,
        )
        content = (resp.choices[0].message.content or "").strip().lower()[:60]
        ok = "red" in content
        return ok, content or "(empty)"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:140]}"


def test_tools(client: OpenAI, model: str) -> tuple[bool, str]:
    if is_claude(model):
        try:
            r = anthropic_post(
                "/messages",
                {
                    "model": model,
                    "max_tokens": 500,
                    "tools": [
                        {
                            "name": "get_weather",
                            "description": "Get the current weather in a city.",
                            "input_schema": {
                                "type": "object",
                                "properties": {"city": {"type": "string"}},
                                "required": ["city"],
                            },
                        }
                    ],
                    "messages": [
                        {"role": "user", "content": "Use the tool to get the weather in Buenos Aires."}
                    ],
                },
            )
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}: {r.text[:140]}"
            data = r.json()
            tool_uses = [b for b in data.get("content", []) if b.get("type") == "tool_use"]
            if tool_uses:
                tu = tool_uses[0]
                return tu.get("name") == "get_weather", f"called {tu.get('name')}({json.dumps(tu.get('input', {}))[:60]})"
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            return False, f"no tool_use; content={text[:60]}"
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)[:140]}"

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the current weather in a city.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": "Use the tool to get the weather in Buenos Aires.",
                }
            ],
            tools=tools,
            tool_choice="auto",
            max_completion_tokens=500,
        )
        msg = resp.choices[0].message
        tc = (msg.tool_calls or []) if hasattr(msg, "tool_calls") and msg.tool_calls else []
        if tc:
            name = tc[0].function.name
            args = tc[0].function.arguments[:80]
            return name == "get_weather", f"called {name}({args})"
        return False, f"no tool_calls; content={(msg.content or '')[:60]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:140]}"


def main() -> None:
    if len(sys.argv) > 1:
        models = sys.argv[1:]
    elif os.environ.get("MODELS"):
        models = [m.strip() for m in os.environ["MODELS"].split(",") if m.strip()]
    else:
        models = DEFAULT_MODELS

    client = make_client()
    base_url = os.environ.get("AZURE_FOUNDRY_BASE_URL", "?")
    print(f"Smoke test: {len(models)} modelos contra {base_url}")
    print()
    print(f"{'Model':<32}  Text   Vision  Tools   Notes")
    print("-" * 110)

    results = []
    for m in models:
        t_ok, t_msg = test_text(client, m)
        v_ok, v_msg = test_vision(client, m) if t_ok else (False, "skipped (text failed)")
        tl_ok, tl_msg = test_tools(client, m) if t_ok else (False, "skipped (text failed)")

        marks = {True: "OK", False: "FAIL"}
        notes_parts = []
        if not t_ok:
            notes_parts.append(f"TEXT[{t_msg}]")
        else:
            if not v_ok:
                notes_parts.append(f"VISION[{v_msg}]")
            if not tl_ok:
                notes_parts.append(f"TOOLS[{tl_msg}]")
        notes = " ".join(notes_parts)[:70]
        print(f"{m:<32}  {marks[t_ok]:<6} {marks[v_ok]:<7} {marks[tl_ok]:<6}  {notes}")
        results.append(
            {
                "model": m,
                "text": t_ok,
                "vision": v_ok,
                "tools": tl_ok,
                "text_msg": t_msg,
                "vision_msg": v_msg,
                "tools_msg": tl_msg,
            }
        )

    print()
    fully_ready = [r for r in results if r["text"] and r["vision"] and r["tools"]]
    text_only = [r for r in results if r["text"] and not r["vision"]]
    tools_missing = [r for r in results if r["text"] and r["vision"] and not r["tools"]]
    unreachable = [r for r in results if not r["text"]]

    print(f"[OK] Fully ready ({len(fully_ready)}):       {', '.join(r['model'] for r in fully_ready) or '-'}")
    print(f"[!]  Text only ({len(text_only)}):          {', '.join(r['model'] for r in text_only) or '-'}")
    print(f"[!]  Tools missing ({len(tools_missing)}):      {', '.join(r['model'] for r in tools_missing) or '-'}")
    print(f"[X]  Unreachable ({len(unreachable)}):       {', '.join(r['model'] for r in unreachable) or '-'}")

    out_dir = Path("experiments/E008_multimodel")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "smoke_test_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
