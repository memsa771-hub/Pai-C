set -e
R="Two independent curl downloads, parsed by two different parsers (python stdlib html.parser tr walk; lxml XPath table cells) to the same output spec; the raw pages differ only in Cloudflare's per-request data-cfemail footer value, and with it blanked they are identical (normalised doc_sha256); the identical derived CSV bytes are agreement, not a copy (controller ruling 2026-11-15, for the owner to confirm)"
B=../docs/research/batches/w12/ajk
for k in postgraduate degree model-science inter; do
  python -m scripts.os_list_sheet --lists ../docs/research/lists --list ajk-hed-$k-colleges --country PK \
    --e1 $B/E1/ajk-hed-$k-colleges.csv --e2 $B/E2/ajk-hed-$k-colleges.csv \
    --e1-method "python stdlib html.parser tr walk" --e2-method "lxml XPath table cells" --mapping $B/mappings/$k.yaml \
    --checker1 claude-w12-ajk-e1 2026-11-15 --checker2 claude-w12-ajk-e2 2026-11-15 \
    --identical-extractions "$R" \
    --out ../docs/research/batches/PAI-Research-W12-ajk-hed-$k-colleges.xlsx
  echo "exit=$?"
done
