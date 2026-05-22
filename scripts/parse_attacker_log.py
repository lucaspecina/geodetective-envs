"""Parsea el stdout log del atacante (cuando crasheó al escribir) y reconstruye
un results.json mínimo: cid, decision, dist_min, confs por run, bucket.

Pierde: lat/lon predichas por run, raw_response. Suficiente para tier classification.

Uso:
  python scripts/parse_attacker_log.py <log_path> <candidates_path> <out_results_path>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LINE_RE = re.compile(
    r"\[\s*\d+/\d+\]\s+"
    r"(?P<tag>[^\s]+)\s+"
    r"#(?P<cid>\d+)\s+"
    r"(?P<bucket>[\w\-]+)\s*/(?P<decada>\d+s)\s+"
    r"dist=\s*(?P<dist>N/A|\d+)(?:km)?\s+"
    r"conf=(?P<confs>[\w\-/]+)\s+"
    r"(?P<decision>keep|reject_attacker|skip)"
)


def main():
    log_path = Path(sys.argv[1])
    candidates_path = Path(sys.argv[2])
    out_path = Path(sys.argv[3])

    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    by_cid = {c["cid"]: c for c in candidates}

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    parsed = 0
    not_matched = 0
    results = []

    for line in lines:
        m = LINE_RE.search(line)
        if not m:
            continue
        cid = int(m.group("cid"))
        if cid not in by_cid:
            not_matched += 1
            continue
        c = by_cid[cid]
        dist_s = m.group("dist")
        dist_min = None if dist_s == "N/A" else float(dist_s)
        confs = m.group("confs").split("/")
        decision = m.group("decision")

        # Reconstruir runs aproximadas (solo conf, dist_min asignada al primer run con conf>=media)
        runs = []
        for conf in confs:
            runs.append({
                "raw_response": "",
                "parsed": {},
                "distance_km": None,  # no sabemos por-run, solo el min
                "confidence": conf,
            })

        # Heuristic: asignar dist_min al primer run con conf media/alta si dist<10
        # (para que classify() reconstruido funcione igual)
        if dist_min is not None:
            assigned = False
            if dist_min < 10:
                for r in runs:
                    if r["confidence"] in {"media", "alta"} and not assigned:
                        r["distance_km"] = dist_min
                        assigned = True
                        break
            if not assigned:
                # asignar al primer run con conf no vacía
                for r in runs:
                    if r["confidence"]:
                        r["distance_km"] = dist_min
                        break

        result = {
            "cid": cid,
            "provider": c.get("provider"),
            "country": c.get("country"),
            "bucket_pais": c["bucket_pais"],
            "bucket_decada": c["bucket_decada"],
            "year": c.get("year"),
            "geo": c["geo"],
            "file_url": c.get("file_url"),
            "page_url": c.get("page_url"),
            "decision": decision,
            "runs": runs,
            "stats": {
                "dist_min": dist_min,
                "dist_median": dist_min,
                "dist_max": dist_min,
                "n_with_coords": sum(1 for r in runs if r["distance_km"] is not None),
                "confidences": confs,
            },
            "attacker_model": "gpt-4o",
            "attacker_prompt_version": "v1",
            "_reconstructed_from_log": True,
        }
        results.append(result)
        parsed += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    decisions = {}
    for r in results:
        decisions[r["decision"]] = decisions.get(r["decision"], 0) + 1

    print(f"parsed:    {parsed} líneas")
    print(f"unmatched: {not_matched}")
    print(f"wrote:     {out_path}")
    print(f"\nDecisiones:")
    for d, n in sorted(decisions.items()):
        print(f"  {d:<20}: {n}")


if __name__ == "__main__":
    main()
