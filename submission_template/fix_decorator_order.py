import re
from pathlib import Path

ROOT = Path("model_weights/vendor/lerobot")

for p in sorted(ROOT.rglob("*.py")):
    text = p.read_text(encoding="utf-8")
    if "_PTV(" not in text:
        continue
    lines = text.splitlines()
    out, i, changed = [], 0, False
    while i < len(lines):
        if re.match(r"^\s*@", lines[i]):
            deco = []
            while i < len(lines) and re.match(r"^\s*@", lines[i]):
                deco.append(lines[i]); i += 1
            tv = []
            while i < len(lines) and re.match(r'^\s*\w+ = _PTV\(', lines[i]):
                tv.append(lines[i]); i += 1
            if tv:
                changed = True
            out.extend(tv)
            out.extend(deco)
            continue
        out.append(lines[i]); i += 1
    if changed:
        p.write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"fixed: {p}")
print("done")
