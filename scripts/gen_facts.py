"""Turn data/sample.json into MeTTa facts inside omega-plugin/tennis/tennis.metta.

One source of truth: the web app reads sample.json, Omega reads the facts this
script writes. Run it again after editing the sample data:

    python scripts/gen_facts.py
"""
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "sample.json"
PLUGIN = ROOT / "omega-plugin" / "tennis" / "tennis.metta"
BEGIN = ";; ---- BEGIN GENERATED FACTS (scripts/gen_facts.py) ----"
END = ";; ---- END GENERATED FACTS ----"


def q(s):
    return '"' + str(s).replace('"', "'") + '"'


def num(x):
    return f"{float(x):.1f}"


def travel_km(p, c):
    return round(math.hypot(p["x"] - c["x"], p["y"] - c["y"]), 1)


def build(data):
    lines = [BEGIN, ";; SAMPLE DATA ONLY - invented players and courts, no real player data."]
    lines.append(";; (player id name level max-travel-km preferred-surface area)")
    for p in data["players"]:
        lines.append(f"(player {q(p['id'])} {q(p['name'])} {num(p['level'])} {num(p['max_travel_km'])} {q(p['surface'])} {q(p['area'])})")
    lines.append(";; (available player day hour)")
    for pid, days in data["availability"].items():
        for day, hours in days.items():
            for h in hours:
                lines.append(f"(available {q(pid)} {q(day)} {h})")
    lines.append(";; (court id name surface) and (court-open court day hour)")
    for c in data["courts"]:
        lines.append(f"(court {q(c['id'])} {q(c['name'])} {q(c['surface'])})")
        for day, hours in c["open"].items():
            for h in hours:
                lines.append(f"(court-open {q(c['id'])} {q(day)} {h})")
    lines.append(";; (travel player court km) - straight-line km on the sample map")
    for p in data["players"]:
        for c in data["courts"]:
            lines.append(f"(travel {q(p['id'])} {q(c['id'])} {num(travel_km(p, c))})")
    lines.append(";; (played a b) - past matches")
    for a, b in data.get("played", []):
        lines.append(f"(played {q(a)} {q(b)})")
    lines.append(END)
    return "\n".join(lines)


def main():
    data = json.loads(DATA.read_text())
    src = PLUGIN.read_text()
    block = build(data)
    pattern = re.compile(re.escape(BEGIN) + ".*?" + re.escape(END), re.S)
    if pattern.search(src):
        src = pattern.sub(lambda _: block, src)
    else:
        src = src.rstrip() + "\n\n" + block + "\n"
    PLUGIN.write_text(src)
    print(f"Wrote {block.count(chr(10)) - 1} fact lines into {PLUGIN.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
