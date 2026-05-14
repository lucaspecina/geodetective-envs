"""Smoke test del adapter: corre 1 foto del pilot E005 con 2 modelos:
- gpt-5.4 (OpenAI path, debe seguir como antes — regresión).
- claude-opus-4-6 (Anthropic path nuevo, debe llegar al final).

max_steps reducido a 5 para ciclo rápido.

Uso:
    python scripts/test_adapter_smoke.py                # gpt-5.4 + claude-opus-4-6
    python scripts/test_adapter_smoke.py gpt-5.4        # solo uno
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# UTF-8 stdout en Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Cargar .env
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(Path("src").resolve()))
from geodetective.agents.react import run_react_agent
from geodetective.corpus import CLEAN_VERSION


PHOTOS_DIR = Path("experiments/E004_attacker_filter/photos")
DEFAULT_CID = 2126812  # Tomsk Russia 1898 — el caso paradigmático
DEFAULT_MODELS = ["gpt-5.4", "claude-opus-4-6"]


def run_one(model: str, cid: int, max_steps: int = 5) -> dict:
    img_path = PHOTOS_DIR / f"{cid}_clean_v{CLEAN_VERSION}.jpg"
    if not img_path.exists():
        return {"model": model, "error": f"image not found: {img_path}"}

    print(f"\n{'=' * 80}")
    print(f"[smoke] model={model} cid={cid} max_steps={max_steps}")
    print(f"{'=' * 80}")
    t0 = time.time()
    try:
        res = run_react_agent(
            image_path=img_path,
            model=model,
            max_steps=max_steps,
            verbose=True,
        )
    except Exception as e:
        import traceback
        return {
            "model": model,
            "error": f"{type(e).__name__}: {str(e)[:500]}",
            "traceback": traceback.format_exc()[:2000],
        }
    elapsed = time.time() - t0

    summary = {
        "model": model,
        "elapsed_seconds": round(elapsed, 1),
        "steps_used": res.steps_used,
        "submit_called": res.submit_called,
        "terminal_state": res.terminal_state,
        "error": res.error,
        "tools_used": {
            "web_search": res.web_search_count,
            "fetch_url": res.fetch_url_count,
            "image_search": res.image_search_count,
            "crop": res.crop_count,
            "geocode": res.geocode_count,
            "historical_query": res.historical_query_count,
            "static_map": res.static_map_count,
            "street_view": res.street_view_count,
        },
        "trace_events": len(res.trace),
        "thinking_blocks_count": sum(1 for t in res.trace if t.get("type") == "thinking_block"),
        "final_answer": res.final_answer,
    }
    print(f"\n[smoke result] {model}: {json.dumps(summary, ensure_ascii=False, indent=2)}")
    return summary


def main() -> None:
    models = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_MODELS
    cid = int(os.environ.get("CID", str(DEFAULT_CID)))
    max_steps = int(os.environ.get("MAX_STEPS", "5"))

    results = []
    for m in models:
        try:
            r = run_one(m, cid, max_steps)
        except Exception as e:
            import traceback
            r = {"model": m, "fatal": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[:2000]}
        results.append(r)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for r in results:
        if r.get("error") or r.get("fatal"):
            print(f"  ❌ {r['model']}: {r.get('error') or r.get('fatal')}")
        else:
            ans = r.get("final_answer") or {}
            tools = r.get("tools_used", {})
            tools_str = " ".join(f"{k}={v}" for k, v in tools.items() if v)
            print(
                f"  ✓ {r['model']}: steps={r['steps_used']} submit={r['submit_called']} "
                f"terminal={r['terminal_state']} tools=[{tools_str}] "
                f"thinking_blocks={r['thinking_blocks_count']} "
                f"loc={ans.get('location', '?')[:50] if ans else 'NONE'}"
            )

    out = Path("experiments") / "adapter_smoke_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
