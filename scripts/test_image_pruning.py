"""Smoke test sintético del cleanup de imágenes (fix bug Azure 50 imgs limit).

Construye un historial sintético con N imágenes (>50) y verifica:
- count_images cuenta bien
- prune_old_images respeta foto target (primera imagen)
- prune_old_images llega a target_count
- text descriptors NO se eliminan
- markers de reemplazo son válidos para Anthropic (type='text')
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geodetective.agents.react import _count_images_in_messages, _prune_old_images


def build_synthetic_messages(n_extra_images: int = 50) -> list[dict]:
    """Construye un historial similar al de un agente con muchas imágenes inyectadas."""
    messages = [
        {"role": "system", "content": "system prompt"},
        # User inicial con foto target
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Investigá esta foto."},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,TARGET_PHOTO_FAKE"}},
            ],
        },
    ]
    # Simular N turns con crops/street_views/image_searches
    for i in range(n_extra_images):
        # Assistant emite tool_call
        messages.append({
            "role": "assistant",
            "content": "thinking",
            "tool_calls": [{"id": f"call_{i}", "type": "function",
                            "function": {"name": "crop_image", "arguments": "{}"}}],
        })
        # Tool result
        messages.append({"role": "tool", "tool_call_id": f"call_{i}", "content": "{}"})
        # User con imagen inyectada (descriptor + image)
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": f"[Crop step={i}, region=test]"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,CROP_{i}"}},
            ],
        })
    return messages


def test_count():
    """Count debe ser exacto: 1 target + N extras."""
    msgs = build_synthetic_messages(n_extra_images=50)
    count = _count_images_in_messages(msgs)
    assert count == 51, f"expected 51, got {count}"
    print(f"  OK count == 51 (1 target + 50 extras)")


def test_prune_basic():
    """Pruning con target=40 debe eliminar 11 (51 - 40)."""
    msgs = build_synthetic_messages(n_extra_images=50)
    removed = _prune_old_images(msgs, target_count=40)
    after = _count_images_in_messages(msgs)
    assert removed == 11, f"expected removed=11, got {removed}"
    assert after == 40, f"expected after=40, got {after}"
    print(f"  OK pruning removed 11, after=40")


def test_target_preserved():
    """La primera imagen (foto target) NO debe ser eliminada."""
    msgs = build_synthetic_messages(n_extra_images=50)
    _prune_old_images(msgs, target_count=40)
    # foto target sigue en messages[1].content
    target_part = next(p for p in msgs[1]["content"] if p.get("type") == "image_url")
    assert "TARGET_PHOTO_FAKE" in target_part["image_url"]["url"]
    print(f"  OK foto target preservada")


def test_descriptors_preserved():
    """Los text descriptors antes de cada imagen NO deben eliminarse."""
    msgs = build_synthetic_messages(n_extra_images=50)
    _prune_old_images(msgs, target_count=40)
    # Contar text parts con [Crop step=...]
    crop_descriptors = 0
    for m in msgs:
        if isinstance(m.get("content"), list):
            for p in m["content"]:
                if isinstance(p, dict) and p.get("type") == "text":
                    if "[Crop step=" in p.get("text", ""):
                        crop_descriptors += 1
    assert crop_descriptors == 50, f"expected 50 descriptors preserved, got {crop_descriptors}"
    print(f"  OK 50 text descriptors preservados")


def test_markers_are_text_type():
    """Los markers de reemplazo deben ser type='text' (compatible con Anthropic adapter)."""
    msgs = build_synthetic_messages(n_extra_images=50)
    _prune_old_images(msgs, target_count=40)
    markers = 0
    for m in msgs:
        if isinstance(m.get("content"), list):
            for p in m["content"]:
                if isinstance(p, dict) and p.get("type") == "text":
                    if "imagen eliminada del contexto" in p.get("text", ""):
                        markers += 1
    assert markers == 11, f"expected 11 markers, got {markers}"
    print(f"  OK 11 markers type='text' (Anthropic-compatible)")


def test_no_prune_when_under_target():
    """Si count <= target, no eliminar nada."""
    msgs = build_synthetic_messages(n_extra_images=30)
    removed = _prune_old_images(msgs, target_count=40)
    assert removed == 0, f"expected removed=0, got {removed}"
    after = _count_images_in_messages(msgs)
    assert after == 31, f"expected after=31, got {after}"
    print(f"  OK no-op cuando count <= target")


def test_message_structure_intact():
    """messages[0] (system) y messages[1] (user inicial) deben quedar bien formados."""
    msgs = build_synthetic_messages(n_extra_images=50)
    _prune_old_images(msgs, target_count=40)
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "system prompt"
    assert msgs[1]["role"] == "user"
    assert isinstance(msgs[1]["content"], list)
    assert len(msgs[1]["content"]) == 2
    print(f"  OK estructura system + user inicial intacta")


if __name__ == "__main__":
    print("Running synthetic tests for image pruning...")
    test_count()
    test_prune_basic()
    test_target_preserved()
    test_descriptors_preserved()
    test_markers_are_text_type()
    test_no_prune_when_under_target()
    test_message_structure_intact()
    print("\nALL TESTS PASSED ✓")
