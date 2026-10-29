"""Fill in your GitHub username and name: python scripts/personalize.py <github-username> "<Your Name>" """
import pathlib
import sys

if len(sys.argv) != 3:
    sys.exit('Usage: python scripts/personalize.py <github-username> "<Your Name>"')
user, name = sys.argv[1], sys.argv[2]
root = pathlib.Path(__file__).resolve().parent.parent
for rel in ("README.md", "docs/index.html"):
    p = root / rel
    p.write_text(p.read_text(encoding="utf-8").replace("YOUR-USERNAME", user), encoding="utf-8")
lic = root / "LICENSE"
lic.write_text(lic.read_text(encoding="utf-8").replace("Copyright (c) 2026", f"Copyright (c) 2026 {name}"), encoding="utf-8")
print(f"Done. Links now point to github.com/{user}/docflow-ai")
