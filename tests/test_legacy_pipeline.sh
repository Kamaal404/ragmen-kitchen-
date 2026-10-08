#!/usr/bin/env bash
# Offline smoke test.
#
# Covers every stage that needs neither an LLM key nor a running database:
# segmentation of plain text and markdown, cross-reference typing, and profile
# validity. PDF checks run only when you point PDF at a document you own:
#
#   PDF=/path/to/your.pdf ./tests/test_legacy_pipeline.sh
#
# No corpus is shipped with this repository, so every text fixture below is
# generated inside the temporary work directory.
set -euo pipefail

cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

pass=0; fail=0
check() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    printf '  \033[32mPASS\033[0m %s\n' "$name"; pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m %s\n' "$name"; fail=$((fail+1))
  fi
}

expect() {   # expect <name> <expected> <actual>
  if [ "$2" = "$3" ]; then
    printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m %s (expected %s, got %s)\n' "$1" "$2" "$3"; fail=$((fail+1))
  fi
}

echo "profiles parse and declare a closed schema"
for p in src/ragmen/cook/profiles/*.yaml; do
  check "$(basename "$p")" "$PY" - "$p" <<'EOF'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
s = d["schema"]
assert d["segmentation"]["chunk_at"], "chunk_at missing"
assert s["node_types"] and s["relationship_types"] and s["patterns"]
# An open schema is the single most common cause of a hairball graph.
for k in ("additional_node_types", "additional_relationship_types", "additional_patterns"):
    assert s.get(k) is False, f"{k} must be false"
labels = {n if isinstance(n, str) else n["label"] for n in s["node_types"]}
rels = {r if isinstance(r, str) else r["label"] for r in s["relationship_types"]}
for src, rel, dst in s["patterns"]:
    assert src in labels and dst in labels, f"pattern endpoint not declared: {src}/{dst}"
    assert rel in rels, f"pattern relation not declared: {rel}"
assert d["retrieval"]["expansion_query"].strip()
EOF
done

echo
echo "legal text: article segmentation and cross-reference typing"
mkdir -p "$WORK/legal"
cat > "$WORK/legal/code.txt" <<'EOF'
TITRE I - DISPOSITIONS GENERALES

CHAPITRE 1 - Champ d'application

Article 1
Le present code s'applique aux relations de travail.

Article 2
Les dispositions sont d'ordre public.

Article 3
Toute infraction a l'article 2 est punie.
EOF
"$PY" src/ragmen/cook/segment.py --profile legal --input "$WORK/legal/code.txt" \
  --out "$WORK/legal.jsonl" --pdf-cache "$WORK/cache-text" >/dev/null 2>&1
expect "one chunk per article" "1 2 3" \
  "$("$PY" -c "import json,sys; print(' '.join(json.loads(l)['number'] for l in open(sys.argv[1])))" "$WORK/legal.jsonl")"
expect "article 3 refers to article 2 once" "1" \
  "$("$PY" -c "import json,sys; rows=[json.loads(l) for l in open(sys.argv[1])]; print(sum(1 for r in rows if r['number']=='3' for x in r['xrefs'] if x['raw']=='2'))" "$WORK/legal.jsonl")"
expect "no chunk references itself" "0" \
  "$("$PY" -c "import json,sys; rows=[json.loads(l) for l in open(sys.argv[1])]; print(sum(1 for r in rows for x in r['xrefs'] if x['raw']==r['number']))" "$WORK/legal.jsonl")"

echo
echo "recipes: title capture and cross-reference resolution"
mkdir -p "$WORK/recipes"
cat > "$WORK/recipes/weeknight.md" <<'EOF'
# Weeknight

## Lemon Garlic Pasta

### Ingredients
- pasta
- lemon

### Instructions
Boil the pasta. See "Garlic Bread" for a side.

## Garlic Bread

### Ingredients
- bread
EOF
"$PY" src/ragmen/cook/segment.py --profile recipes --input "$WORK/recipes" \
  --out "$WORK/r.jsonl" --pdf-cache "$WORK/cache-recipes" >/dev/null 2>&1
expect "recipe corpus chunks" "2" "$(wc -l < "$WORK/r.jsonl" | tr -d ' ')"
check "recipe title captured" grep -q '"title": "Lemon Garlic Pasta"' "$WORK/r.jsonl"
check "recipe cross-ref resolved" grep -q 'PAIRS_WITH' "$WORK/r.jsonl"

if [ -n "${PDF:-}" ]; then
  echo
  echo "PDF pipeline ($PDF)"
  [ -f "$PDF" ] || { echo "  PDF not found: $PDF"; exit 2; }
  check "diagnose detects a text layer" \
    "$PY" src/ragmen/cook/extract_pdf.py --input "$PDF" --out "$WORK/d" --diagnose-only
  "$PY" src/ragmen/cook/extract_pdf.py --input "$PDF" --out "$WORK/x" >/dev/null 2>&1
  check "extraction writes text" bash -c "ls '$WORK/x'/*.txt >/dev/null 2>&1"
  check "extraction writes a page map" bash -c "ls '$WORK/x'/*.pages.json >/dev/null 2>&1"

  echo
  echo "segmentation, all three PDF engines agree"
  sigs=()
  for engine in poppler pdfplumber pypdf; do
    rm -rf "$WORK/cache"
    if ! "$PY" src/ragmen/cook/segment.py --profile legal --input "$PDF" \
          --out "$WORK/c-$engine.jsonl" --pdf-cache "$WORK/cache" \
          --pdf-engine "$engine" >/dev/null 2>&1; then
      printf '  \033[31mFAIL\033[0m %s segmentation errored\n' "$engine"; fail=$((fail+1)); continue
    fi
    sig=$("$PY" -c "import json,sys; rows=[json.loads(l) for l in open(sys.argv[1])]; print(' '.join(f\"{r['number']}@{r.get('page')}\" for r in rows))" "$WORK/c-$engine.jsonl")
    sigs+=("$sig")
    printf '  \033[32mPASS\033[0m %s produced %s chunks\n' "$engine" "$(wc -l < "$WORK/c-$engine.jsonl" | tr -d ' ')"; pass=$((pass+1))
  done
  if [ "${#sigs[@]}" -gt 0 ]; then
    for s in "${sigs[@]}"; do expect "engine output matches" "${sigs[0]}" "$s"; done
  fi
else
  echo
  echo "PDF checks skipped. Set PDF=/path/to/your.pdf to run them."
fi

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1
