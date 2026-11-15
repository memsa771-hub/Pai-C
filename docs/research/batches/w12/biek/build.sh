set -e
R="Two independent curl downloads (same raw page sha256) parsed by two different parsers (python stdlib html.parser; lxml 6.1.3 DOM) to the same output spec; whole-page text hashes differ; the identical CSV bytes are agreement, not a copy (controller ruling 2026-11-15, for the owner to confirm)"
B=../docs/research/batches/w12/biek
for pair in "government:GOV" "private:PVT"; do
  k=${pair%%:*}
  python -m scripts.os_list_sheet --lists ../docs/research/lists --list biek-affiliated-$k-colleges --country PK \
    --e1 $B/E1/biek-affiliated-$k-colleges.csv --e2 $B/E2/biek-affiliated-$k-colleges.csv \
    --e1-method "python stdlib html.parser" --e2-method "lxml 6.1.3 DOM" --mapping $B/mappings/$k.yaml \
    --checker1 claude-w12-biek-e1 2026-11-15 --checker2 claude-w12-biek-e2 2026-11-15 \
    --identical-extractions "$R" \
    --out ../docs/research/batches/PAI-Research-W12-biek-affiliated-$k-colleges.xlsx
  echo "exit=$?"
done
