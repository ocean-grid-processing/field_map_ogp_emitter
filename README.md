# mld_emitter

`mld_emitter` packages one `ohc_derive` blob into a **gridded field map with its ensemble spread** — one
NetCDF, `<name>_map_<tag>_<data>_<product_name>_<author>.nc` (`mld_map_…` for a mixed layer depth), ME4OH
layout, monthly, per grid cell.

```
ohc_ingest ─▶ publish ─▶ ohc_derive (identity level, --quantities field) ─▶ mld_emitter ─▶ map .nc
```

The analysis is all upstream. For a single-layer quantity `ohc_derive` builds the identity level: the
`as_published` mask takes the submission's mask as final (and verifies it is time-constant), the
`field` quantity carries the field through on the grid, and the collapse gives the per-cell mean and
the member 1-sigma. Its blob hands over `field` (with `field_sd` when the ensemble was on) in the
published units — `field_units` on each variable — plus the `quantity` table and the `level` token
it was mapped under. This emitter is only the packaging: lay the grid out in ME4OH order, name the
variables after the quantity, and write. **Nothing is scaled.**

## What it computes

```
mld(x, t)     = blob.field       # m, the posterior-mean mixed layer depth, as published
mld_std(x, t) = blob.field_sd    # m, per-cell ensemble 1-sigma, present when the ensemble was on
```

The variable names come from the `quantity` table's `name` (`mld` → `mld`, `mld_std`); the units from
`field_units`; the `long_name` from the table. The grid keeps its **native monthly TIME axis** from the
submission (re-encoded to days-since-1900 on write — the loader decodes it, so the units are pinned
back). `LONGITUDE`/`LATITUDE` and their attrs carry straight from the blob.

**Spread convention.** `mld_std` is derive's member spread of the published field — the same number
`publish.py` writes as `DATA_SD`, since neither step transforms the field before taking the spread.

## Building the input

One `ohc_derive` blob, built from the single submission with no `--level` (the identity level) and
`--quantities field`:

```bash
python ../ohc_derive/run.py MLD_<tag>_<Y0>_<Y1>_lev<a>_<b>.nc \
    --bathy etopo60.cdf --quantities field \
    --tag <tag> --code-version URL --product-name <p> --author <a> --citation "<c>" --out <dir>
```

The blob **must** carry data var **`field`** (its **`field_sd`** companion when the derive run kept
the ensemble; the emitter skips `_std` when it is absent), and the attrs **`quantity`** and
**`level`**. The emitter errors if `field` or `quantity` is missing.

## Output

One file per blob:

- data vars **`<name>(LONGITUDE, LATITUDE, TIME)`** and **`<name>_std`**, `_FillValue = -999`;
- global attrs **`level`** (the native token the field was mapped under — a name, not a depth range),
  **`provenance_tag`**, **`provenance_link`**, **`citation`**, **`product_name`**, and one
  **`config_record`** holding the whole provenance chain (ingest → publish → derive → this step),
  keyed by stage. Six attrs (seven with `_NCProperties`) keeps the file in HDF5 compact storage.

## Usage

### Environment

`Dockerfile` builds the test/run environment; make the equivalent conda env on the cluster.

### Test

```
docker image build -t mld_emitter:test .
docker container run -v $(pwd):/app mld_emitter:test pytest
```

### Run

See `emit.slurm` for the cluster invocation (one job, one blob). Options:

| option | default | effect |
|---|---|---|
| `BLOB.nc …` (positional) | *(required)* | the `ohc_derive` blob(s) built with `--quantities field`; one output file per blob |
| `--tag` | *(required)* | provenance tag: the run token in the filename and the `provenance_tag` attr. Whitespace-stripped, never lowercased |
| `--provenance-link` | *(none)* | URL/path to the provenance record; the `provenance_link` attr |
| `--code-version` | *(required)* | URL to the exact `mld_emitter` code (commit/release); stamped in `config_record` |
| `--product-name` | *(required)* | first of the filename's trailing pair; also the `product_name` attr |
| `--author` | *(required)* | last of the filename's trailing pair |
| `--citation` | *(required)* | citation sentence; the top-level `citation` attr |
| `--out` | `.` | output directory |
