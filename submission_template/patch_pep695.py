import re
from pathlib import Path

ROOT = Path("model_weights/vendor/lerobot")
IMPORT_LINE = "from typing import TypeVar as _PTV, Generic as _PGen\n"

DEF_RE = re.compile(r"^(\s*)(def\s+\w+)\[([^\]]*)\](\(.*)$")
CLASS_RE = re.compile(r"^(\s*)class\s+(\w+)\[([^\]]*)\](\([^)]*\))?\s*:(.*)$")
TYPE_RE = re.compile(r"^(\s*)type\s+(\w+)\s*=\s*(.*)$")

def split_params(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out

def typevar_defs(paramstr, indent):
    names, defs = [], []
    for p in split_params(paramstr):
        name = p.split(":", 1)[0].strip().lstrip("*")
        names.append(name)
        defs.append(f'{indent}{name} = _PTV("{name}")')
    return names, defs

def ensure_import(text):
    if "_PTV" not in text:
        return text
    if IMPORT_LINE in text:
        return text
    lines = text.splitlines(keepends=True)
    pos = 0
    for i, l in enumerate(lines):
        if (l.startswith("import ") or l.startswith("from ")) and not l.startswith("from __future__"):
            pos = i
            break
    lines.insert(pos, IMPORT_LINE)
    return "".join(lines)

for path in sorted(ROOT.rglob("*.py")):
    text = path.read_text(encoding="utf-8")
    out, changed = [], False
    for line in text.splitlines():
        m = TYPE_RE.match(line)
        if m:
            out.append(f"{m.group(1)}{m.group(2)} = {m.group(3)}")
            changed = True
            continue
        m = DEF_RE.match(line)
        if m:
            indent, defpart, params, rest = m.groups()
            names, defs = typevar_defs(params, indent)
            out.extend(defs)
            out.append(f"{indent}{defpart}{rest}")
            changed = True
            continue
        m = CLASS_RE.match(line)
        if m:
            indent, name, params, bases, tail = m.groups()
            names, defs = typevar_defs(params, indent)
            out.extend(defs)
            generic = f"_PGen[{', '.join(names)}]"
            if bases and bases[1:-1].strip():
                newbases = f"({bases[1:-1].strip()}, {generic})"
            else:
                newbases = f"({generic})"
            out.append(f"{indent}class {name}{newbases}:{tail}")
            changed = True
            continue
        out.append(line)
    if changed:
        newtext = "\n".join(out) + ("\n" if text.endswith("\n") else "")
        newtext = ensure_import(newtext)
        path.write_text(newtext, encoding="utf-8")
        print(f"patched: {path}")
print("done")
