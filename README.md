# field_map_ogp_emitter

`field_map_ogp_emitter` packages one `ogp_derive` blob into a **gridded field map with its ensemble spread**
— one NetCDF, `<name>_map_<tag>_[<level>_dbar_]<data>_<product_name>_<author>.nc` (`mld_map_…` for
a mixed layer depth; the level token appears only for a synthetic level), ME4OH layout, monthly, per
grid cell.

```
localgp_ogp_ingest ─▶ publish ─▶ ogp_derive (identity level, --quantities field) ─▶ field_map_ogp_emitter ─▶ map .nc
```

The analysis is all upstream. For a single-layer quantity `ogp_derive` builds the identity level: the
`as_published` mask takes the submission's mask as final (and verifies it is time-constant), the
`field` quantity carries the field through on the grid, and the collapse gives the per-cell mean and
the member 1-sigma. Its blob hands over `field` (with `field_sd` when the ensemble was on) in the
published units — `field_units` on each variable — plus the `quantity` table and the `level` token
it was mapped under. This emitter is only the packaging: lay the grid out in ME4OH order, name the
variables after the quantity, and write. **Nothing is scaled.**

Nothing in this emitter is specific to any one quantity. It is the generic gridded emitter for
derive's `field` deliverable: the variable names, units and `long_name` all come from the `quantity`
table the ingest config declared, so a different quantity produces a correctly named and labelled file
with no code change — the ingest config is the product definition. Mixed layer depth is the first
product through it. (The OHC anomaly map goes through `map_ogp_emitter` instead, which hard-wires the
OHC scaling and names.)

## What it computes

```
<name>(x, t)     = blob.field       # the posterior-mean field, as published
<name>_std(x, t) = blob.field_sd    # per-cell ensemble 1-sigma, present when the ensemble was on
```

For the LocalGP MLD config, `<name>` is `mld` and the units are the `publish_units` the ingest
`[quantity]` table declared — `dbar` for the mixed layer depth (`config.mld.toml`); the emitter copies
them, it does not interpret them. The `long_name` comes from the table too. The grid keeps its **native monthly TIME
axis** from the submission (re-encoded to days-since-1900 on write — the loader decodes it, so the
units are pinned back). `LONGITUDE`/`LATITUDE` and their attrs carry straight from the blob.

**Spread convention.** `<name>_std` is derive's member spread of the published field — the same
number `publish.py` writes as `DATA_SD`, since neither step transforms the field before taking the
spread. [`validation/field_map_oracle.py`](../validation/field_map_oracle.py) asserts exactly this
(`mld == DATA`, `mld_std == DATA_SD`) against the published submission.

## Building the input

One `ogp_derive` blob, built along the LocalGP single-layer happy path in
[`ogp_derive/examples/derive_mld.slurm`](../ogp_derive/examples/derive_mld.slurm): the single
submission, no `--level`/`--levels` (the identity level), `--quantities field`, `--mask as_published`:

```bash
python ../ogp_derive/run.py MLD_<tag>*.nc \
    --quantities field --mask as_published \
    --bathy etopo60.cdf --tag <tag> --code-version URL \
    --product-name LocalGP --author Giglio_etal2026 --citation "…" --out <dir>
```

The same emitter serves a **synthetic level** of an extensive quantity — an integrated potential
temperature over `0_300`, say — built along the OHC path (`--levels levels/localgp.toml --level 0_300
--mask contiguous_from_top --quantities field`): derive's combine gives the per-cell `Σ n_fac·field_i`
column integral and the linear sum of the constituent spreads, and the emitter packages it unchanged.
The output filename then carries the level, `<name>_map_<tag>_<level>_dbar_<data>_…`, so one
quantity's levels don't collide; an identity level's token names nothing physical and is left out.
Which case applies is read from derive's `ohc_derive_run_facts.identity_level`, never guessed from
the token, and the token itself is copied verbatim (it is not parsed as numbers).

No `--time-window`: the field is delivered as published, not as an anomaly, so there is no baseline
and no `tw<baseline>` token in the output filename. The blob **must** carry data var **`field`** (its
**`field_sd`** companion when the derive run kept the ensemble; the emitter skips `_std` when it is
absent), and the attrs **`quantity`**, **`level`** and **`ohc_derive_run_facts`** (with
`identity_level`). The emitter exits if any of these is missing.

## Usage

### Environment

`Dockerfile` builds the test/run environment; make the equivalent conda env on the cluster.

### Test

```bash
docker image build -t field_map_ogp_emitter:test .
docker container run -v $(pwd):/app field_map_ogp_emitter:test pytest
```

### Run

One blob in, one map out. The happy path is [`emit.slurm`](emit.slurm) (one job, one blob;
[`run.sh`](run.sh) just submits it):

```bash
sbatch emit.slurm
```

or directly:

```bash
python emit.py derive_<tag>_<data>_tw<data>_<level>.nc --tag <tag> --code-version URL \
    --product-name LocalGP --author Giglio_etal2026 --citation "…" [--provenance-link URL] [--out DIR]
```

#### emit.py options

All configuration is on the command line — no env, no config file. Every resolved option lands in
`config_record` (under this stage's `run_config`), except `--citation`, which has its own attr.

| option | required | default | what it does |
|---|:--:|---|---|
| `BLOB.nc …` (positional, 1+) | **yes** | | `ogp_derive` blob(s) built with `--quantities field`; one output file per blob. Each must carry `field`, a `quantity` attr and derive's `ohc_derive_run_facts` |
| `--tag` | **yes** | | provenance tag: the run token in the filename and the `provenance_tag` attr. Whitespace-stripped, never lowercased |
| `--code-version` | **yes** | | URL to the exact `field_map_ogp_emitter` code (commit/release); recorded as this stage's `code_version` inside `config_record` |
| `--product-name` | **yes** | | product_name string; first of the filename's trailing pair (whitespace-stripped, case preserved), a standalone top-level `product_name` attr, and recorded in `config_record` |
| `--author` | **yes** | | author string; last of the filename's trailing pair (e.g. `Giglio_etal2026`) and recorded in `config_record` |
| `--citation` | **yes** | | citation sentence; written to the standalone top-level `citation` attr (kept out of `config_record` so it isn't duplicated) |
| `--provenance-link` | | *(none)* | URL/path to the provenance record; written to the `provenance_link` attr |
| `--out` | | `.` | output directory (created if absent) |

## Output and provenance

One file per blob:

- data vars **`<name>(LONGITUDE, LATITUDE, TIME)`** and **`<name>_std`**, `_FillValue = -999`
  (NaN off-footprint lands as `-999` on disk and decodes back to NaN on read);
- global attrs **`level`** (the level token as derive named it — a native tag for an identity level, a
  plan level like `0_300` for a synthetic one),
  **`provenance_tag`**, **`provenance_link`** (when given), **`citation`**, **`product_name`**, and
  one **`config_record`**.

**Provenance chain.** Each map is built from one derive blob, so this step is a 1-in-1-out courier: it
rolls that blob's whole provenance chain forward (every `*_run_config` / `*_run_facts` /
`*_code_version` — the `localgp_ingest_*` / `localgp_publish_*` and `ohc_derive_*` blocks) and folds
in its own block, emitting the lot as **one** `config_record` attribute keyed by stage:

```
config_record = {
  "localgp_ingest":  {"run_config": {…}, "run_facts": {…}, "code_version": "…"},
  "localgp_publish": {…},
  "ohc_derive":      {…},
  "field_map_ogp_emitter": {"run_config": {resolved args}, "run_facts": {level, quantities_present, ensemble, source_blob}, "code_version": "…"}
}
```

The stage keys are the pipeline's provenance contract: `ohc_derive` is written by `ogp_derive`
(a pre-rename key kept for continuity), and this emitter's own block is keyed
`field_map_ogp_emitter`. Six global attrs (seven with `_NCProperties`) keeps
the file in HDF5 compact attribute storage, which every reader handles; a dozen separate attributes
would tip it into dense (fractal-heap) storage that some netcdf builds mis-read.

For a single-submission identity level there is no per-constituent fan-out to factor, so the forwarded
`localgp_*` blocks arrive as singletons and pass through as they are; for a synthetic level they are
DRY'd into `shared` + `per_constituent` exactly as in `map_ogp_emitter`.
