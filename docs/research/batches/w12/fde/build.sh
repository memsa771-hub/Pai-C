set -e
B=../docs/research/batches/w12/fde
python -m scripts.os_list_sheet --lists ../docs/research/lists --list fde-hssc-participating-colleges --country PK \
  --e1 $B/E1/fde-hssc-participating-colleges.csv --e2 $B/E2/fde-hssc-participating-colleges.csv \
  --e1-method "python stdlib html.parser" --e2-method "lxml XPath table rows" --mapping $B/mapping.yaml \
  --checker1 claude-w12-fde-e1 2026-11-15 --checker2 claude-w12-fde-e2 2026-11-15 \
  --out ../docs/research/batches/PAI-Research-W12-fde-hssc-participating-colleges.xlsx
echo "exit=$?"
