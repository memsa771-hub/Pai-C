set -e
# Extra arguments go to the tool, e.g. `sh build.sh --force` to rebuild over the committed workbook (v2, FU-15).
B=../docs/research/batches/w12/pmdc
python -m scripts.os_list_sheet --lists ../docs/research/lists --list pmdc-colleges-with-hospitals --country PK \
  --e1 $B/E1/pmdc-colleges-with-hospitals.csv --e2 $B/E2/pmdc-colleges-with-hospitals.csv \
  --e1-method "pypdf 7.1.0 fragment x-cut" --e2-method "pypdf 7.1.0 clip-rectangle cells" --mapping $B/mapping.yaml \
  --checker1 claude-w12-pmdc-e1 2026-11-15 --checker2 claude-w12-pmdc-e2 2026-11-15 \
  --out ../docs/research/batches/PAI-Research-W12-pmdc-colleges-with-hospitals.xlsx "$@"
echo "exit=$?"
