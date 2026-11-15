# W12 BIEK affiliated colleges: list workbooks and alias files (2026-11-15, LOCAL)

These are the two BIEK lists in docs/research/lists/sindh.yaml:
- `biek-affiliated-government-colleges`: 181 lines, https://www.biek.edu.pk/gmaleCol.asp;
- `biek-affiliated-private-colleges`: 174 lines, https://www.biek.edu.pk/PMaleCol.asp.

They are loaded as list workbooks built with `backend/scripts/os_list_sheet.py` (P2-T29) from two independent
extractions:
- `docs/research/batches/PAI-Research-W12-biek-affiliated-government-colleges.xlsx`: id_prefix `SD-BIEK-GOV-`, type
  public_college.
- `docs/research/batches/PAI-Research-W12-biek-affiliated-private-colleges.xlsx`: id_prefix `SD-BIEK-PVT-`, type
  private_college.

Each workbook has an alias file next to it (`.aliases.yaml`).

## The two extractions
Each extraction was made by a different agent from its own curl download, made on 2026-11-14 at about 22:21 UTC. The
raw page sha256 is the same for both: gov 778bebc9310d2fffc2d150221f171bb8f3216b625584f581f7bc3ec48095c575, priv
a6da0a0d881dd8de0fcfa921648107d21c9f79c48f12f8451c7ee2d6237f9450. It is recorded in every CSV row (`doc_sha256`) and in
each workbook's `checker_note`.

| | Method label | Parser |
|---|---|---|
| E1 (`E1/`) | python stdlib html.parser | `html.parser`, text of each `<p align='left'>` split at `<br>` |
| E2 (`E2/`) | lxml 6.1.3 DOM | `lxml.html`, text nodes of each `<p align='left'>` walked in document order, split at `<br>` |

Both extractions followed the same output spec:
- quote = `"N. " + name + " " + address`, with whitespace collapsed;
- city = `Karachi` only where the address prints it, and empty otherwise (no misspelling read as the city);
- page empty.

Both decoded the page the same way: UTF-8 kept, and each invalid byte (the list text is cp1252) read as cp1252.
Their whole-page tag-stripped text hashes differ, because the two parsers produce different text nodes (gov d1bc953a... vs
11371a40..., priv 12d81c25... vs bd9581cc...).

### Identical CSV bytes: controller ruling (for the owner to confirm)
E1 and E2 produced byte-identical CSVs for both lists:
- gov 15d07be04e5e0eed850fc1cef9f4f724b6665245c734054df83c974301211af3;
- priv 3c9a789e5d0066fde56d2f9639f7f8f0b32b5b8859f51911bc024e3b0ee5ddae.

The tool refuses two files with the same sha256 unless `--identical-extractions REASON` is given. The controller
allowed it with this reason, which is recorded in each workbook's "Derived from" sheet:

> Two independent curl downloads (same raw page sha256) parsed by two different parsers (python stdlib html.parser;
> lxml 6.1.3 DOM) to the same output spec; whole-page text hashes differ; the identical CSV bytes are agreement, not a
> copy (controller ruling 2026-11-15, for the owner to confirm)

## Build
`build.sh` (run from `backend/`, in `docker run --rm pai-ci-py`) builds both workbooks. It uses:
- the mappings `mappings/government.yaml` and `mappings/private.yaml`, with read_method "curl + HTML text strip" and
  retrieved 2026-11-14;
- checkers `claude-w12-biek-e1` / `claude-w12-biek-e2`, both dated 2026-11-15.

Result: 181 and 174 rows written, 0 held (the `.held.csv` files have only the header).

## Alias files
`make_aliases.py` (run from `backend/`) writes both alias files. Each file is bound to its workbook's sha256. Nothing in
them is typed by hand:
- the verdicts are read from `checks/alias-check1.yaml` (ref `claude-w12-biek-alias-check-1`) and
  `checks/alias-check2.yaml` (ref `claude-w12-biek-alias-check-2`, independent). The script stops if a verdict differs
  from the controller ruling;
- `evidence` is the BIEK line (the list url and the row's `source_quote`);
- `target_evidence` is the target row's `source_url` and `source_quote`, from batch 3 v4 for SD-COL-*, or from the same
  W12 workbook for SD-BIEK-*.

Every alias has `required: true` and is dated 2026-11-15.

Controller ruling: an alias is accepted only where both checks say `same`. The verdicts map to the check columns as
follows:
- check 1: same -> `correct`, unclear -> `unclear`;
- check 2: same -> `yes`. For unclear, `approved` is left empty, because format.yaml `check2_values` has no `unclear`
  (`plan.read_checks` would read it as missing anyway). The verdict is kept in a YAML comment on that alias.

| from | to | check 1 | check 2 | |
|---|---|---|---|---|
| gov 1, 3, 4, 5, 8, 9, 11, 12, 14, 15, 37 | SD-COL-KQ2215, 2172, 2173, 2193, 2167, 2158, 2207, 2273, 2194, 2232, 2339 | same | same | accepted |
| gov 6 | SD-COL-KQ2150 | same | unclear | held |
| gov 7 | SD-COL-KQ2163 | same | unclear | held |
| gov 27 | SD-COL-KQ2236 | unclear | unclear | held |
| gov 181 | SD-BIEK-GOV-95 (same list) | unclear | same | held |
| private 42 | SD-BIEK-PVT-34 (same list) | same | same | accepted |
| private 50 | SD-BIEK-PVT-48 (same list) | unclear | unclear | held |

A held alias is required and not accepted, so its row is rejected (`alias_required_not_accepted`). No duplicate entity
is loaded, and no entity is loaded for that line until two new checks settle it.

## Dry run (validate, 2026-11-15)
The dry run passed `--institutions-from ../docs/research/batches/PAI-Research-Batch3-Sindh-v4.xlsx --aliases <file>
--assume-aliases-attested`.

- **Government file:**
  - Aliases: 11 `alias_applied` and 4 `alias_required_not_accepted`.
  - Institutions: 11 `alias_membership` (adds the BIEK list to the SD-COL-KQ entity), 4 rejected
    `alias_required_not_accepted` (gov 6, 7, 27, 181), and 166 new entities.
- **Private file:**
  - Aliases: 1 `alias_applied` and 1 `alias_required_not_accepted`.
  - Institutions: 1 skipped `aliased` (private 42 -> 34: the target is in the same file and already names the list, so
    nothing is added), 1 rejected (private 50), and 172 new entities.
- All planned rows are `unconfirmed` (`check_unclear_or_missing`). validate runs in owner-accepted mode, which does not
  know the W12 checker refs ("checker 1 is not a check the owner accepted"; FU-12). This is expected and was not tested
  in reviewers mode here.

## Before the import
- Register the reviewer refs `claude-w12-biek-e1` and `claude-w12-biek-e2` (`backend/scripts/os_reviewers.py`). Each
  must attest each workbook's batch ref.
- `claude-w12-biek-alias-check-1` and `-2` must attest each alias file's ref, `aliases-<sha256 of the alias file>`.
- Editing an alias file changes that ref.
