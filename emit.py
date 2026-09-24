#!/usr/bin/env python3
"""Field map packaging: one ohc_derive `field` blob -> the gridded per-cell deliverable.

For a single-layer quantity such as a mixed layer depth, the factory's identity level takes the
published field as it is (`as_published` mask, `field` quantity) and collapses the ensemble to a
per-cell 1-sigma. Its blob carries `field` (with `field_sd` when the ensemble is on) on the native
monthly grid, in the published units (`field_units` on the variable), plus the `quantity` table and
the `level` token it was built under. This step is only the packaging: lay the grid out in the ME4OH
order, name the variables after the quantity, and write one file. Nothing is scaled.

Output: `<name>(LONGITUDE, LATITUDE, TIME)` in the field's units — `mld` in m for a mixed layer depth —
plus `<name>_std` (per-cell ensemble 1-sigma) when the members were present. The grid keeps its native
monthly TIME axis, re-encoded to days-since-1900 on write (the loader decodes it, so we pin the units
back on).
"""
import argparse
import json
import os

import xarray as xr

# This step's identity, used to key its block inside the consolidated `config_record`. Each output file
# is built from one derive blob (one level), so this step is a 1-in-1-out courier: it rolls the blob's
# whole provenance chain forward and folds its own block in, emitting the lot as one `config_record`
# attribute (one attribute keeps the file in HDF5 compact storage — see `stamp_config_record`).
STAGE = "mld_emitter"
_PROV_SUFFIXES = ("_run_config", "_run_facts", "_code_version")


def _compact(obj):
    """One-line JSON — reads as a single clean line in `ncdump -h`."""
    return json.dumps(obj, separators=(",", ":"), default=str)


def _shared_and_per(group_map):
    """{group: block} -> (shared, per): keys present in every group with an equal value go to `shared`;
    everything else stays per group. Lossless — block[g] == {**shared, **per[g]}."""
    groups = list(group_map)
    common = set(group_map[groups[0]])
    for g in groups[1:]:
        common &= set(group_map[g])
    shared = {}
    for k in sorted(common):
        vals = [group_map[g][k] for g in groups]
        if all(v == vals[0] for v in vals):
            shared[k] = vals[0]
    per = {g: {k: v for k, v in group_map[g].items() if k not in shared} for g in groups}
    return shared, per


def _compact_block(block, axis):
    """Factor one fan-out `{group: value}`: object values -> shared + per_<axis> (a fully-shared block
    collapses to the bare shared object); scalar values -> the bare value if all agree, else per_<axis>."""
    values = list(block.values())
    if all(isinstance(v, dict) for v in values):
        shared, per = _shared_and_per(block)
        if not any(per.values()):
            return shared
        return {"shared": shared, "per_" + axis: per}
    if all(v == values[0] for v in values):
        return values[0]
    return {"per_" + axis: dict(block)}


def _maybe_json(v):
    """Parse a forwarded block back to JSON so it nests as a real object; leave non-JSON (a bare
    code_version URL) as-is."""
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return v


def _dry_constituent_fanouts(record):
    """Within the assembled record, factor any per-constituent fan-out into shared + per_constituent
    (lossless). Driven by the constituents roster in `ohc_derive.run_facts`, so only genuine fan-outs
    are touched — a value like `n_fac`, nested inside a non-fanned block, is never a candidate."""
    facts = record.get("ohc_derive", {}).get("run_facts")
    roster = (set(facts["constituents"]) if isinstance(facts, dict)
              and isinstance(facts.get("constituents"), list) else None)
    if not roster:
        return record
    for parts in record.values():
        if not isinstance(parts, dict):
            continue
        for name, val in list(parts.items()):
            if isinstance(val, dict) and len(val) > 1 and set(val) <= roster:
                parts[name] = _compact_block(val, "constituent")
    return record


def stamp_config_record(out, blob, cfg, source_path):
    """Assemble the whole provenance chain into ONE `config_record` attribute, keyed by stage and DRY'd
    per constituent. A single attribute keeps the file at <=8 global attributes, i.e. HDF5 *compact*
    attribute storage — which every reader handles. Emitting a dozen separate `*_run_config` etc. tips
    HDF5 into dense (fractal-heap) storage, whose exact layout some netcdf builds mis-read."""
    record = {}
    # the forwarded chain: group the blob's *_run_config/_run_facts/_code_version by stage
    for k, v in blob.attrs.items():
        for suffix in _PROV_SUFFIXES:
            if k.endswith(suffix):
                record.setdefault(k[:-len(suffix)], {})[suffix[1:]] = _maybe_json(v)
                break
    # this step's own block. citation has its own top-level attr, so keep it out of the brick (not
    # duplicated); product_name/author stay in run_config for the record.
    record[STAGE] = {
        "run_config": {k: v for k, v in vars(cfg).items() if k != "citation"},
        "run_facts": {
            "level": blob.attrs.get("level"),
            "quantity": quantity(blob),
            "quantities_present": [q for q in ("field",) if q in blob],
            "ensemble": "field_sd" in blob,
            "source_blob": os.path.abspath(source_path),
        },
        "code_version": cfg.code_version,
    }
    out.attrs["config_record"] = _compact(_dry_constituent_fanouts(record))


def _me4oh(da):
    """(time, lat, lon) -> (LONGITUDE, LATITUDE, TIME), the ME4OH submission layout."""
    return da.transpose("lon", "lat", "time").rename(
        {"lon": "LONGITUDE", "lat": "LATITUDE", "time": "TIME"})


def quantity(blob):
    """The blob's `quantity` table (the ingest [quantity] attr, carried through derive) -> dict."""
    if "quantity" not in blob.attrs:
        raise SystemExit("blob has no `quantity` attr (expected an ohc_derive blob)")
    return json.loads(blob.attrs["quantity"])


def build_dataset(blob, tag, provenance_link, citation="", product_name=""):
    """A derive `field` blob -> the gridded field deliverable Dataset, ME4OH layout, variables named
    after the quantity (`mld`, `mld_std`), units as the blob carries them."""
    q = quantity(blob)
    name = q["name"]
    units = blob["field"].attrs.get("field_units", q.get("publish_units", ""))

    field = _me4oh(blob["field"])                            # as published: no scaling
    field.attrs = {"units": units, "long_name": q["long_name"]}
    dv = {name: field}
    if "field_sd" in blob:
        sd = _me4oh(blob["field_sd"])
        sd.attrs = {"units": units, "long_name": "%s ensemble standard deviation (1-sigma)" % name}
        dv[name + "_std"] = sd

    out = xr.Dataset(dv)
    for coord, src in (("LONGITUDE", "lon"), ("LATITUDE", "lat")):   # carry coord attrs the loader kept
        if src in blob.coords and blob[src].attrs:
            out[coord].attrs = dict(blob[src].attrs)

    out.attrs["level"] = blob.attrs["level"]                  # the native token the field was mapped under
    out.attrs["provenance_tag"] = tag
    if provenance_link is not None:
        out.attrs["provenance_link"] = provenance_link
    out.attrs["citation"] = citation
    if product_name:
        out.attrs["product_name"] = product_name   # top-level discoverable key (also in config_record)
    return out


def _data_span(blob):
    """`YYYY_YYYY` for the years the blob's own axis spans (`year` annual, `time` monthly)."""
    if "year" in blob.coords:
        yrs = blob["year"].values.astype(int)
        return "%d_%d" % (int(yrs.min()), int(yrs.max()))
    if "time" in blob.coords:
        yrs = blob["time"].values.astype("datetime64[Y]").astype(int) + 1970
        return "%d_%d" % (int(yrs.min()), int(yrs.max()))
    return "all"


def _file_token(blob):
    """Filename token: the blob's own data span `<data>`. The field is not baseline-referenced, so there
    is no `tw<baseline>` here, and the level token names nothing physical, so it is left out too."""
    return _data_span(blob)


def filename(name, tag, token, product_name, author):
    """Map name: <name>_map_<tag>_<data>_<product_name>_<author>.nc (tag leads after the step;
    product_name/author are the last thing before .nc)."""
    return "%s_map_%s_%s_%s_%s.nc" % (name, tag, token, product_name, author)


def main():
    ap = argparse.ArgumentParser(description="field map packaging: ohc_derive `field` blob -> gridded deliverable")
    ap.add_argument("blobs", nargs="+", help="ohc_derive output NetCDFs built with --quantities field")
    ap.add_argument("--tag", required=True, help="provenance tag: filename token + provenance_tag attr")
    ap.add_argument("--provenance-link", default=None, help="URL/path to the provenance record")
    ap.add_argument("--code-version", required=True,
                    help="URL to the exact mld_emitter code (commit/release); stamped in config_record")
    ap.add_argument("--product-name", required=True,
                    help="product_name string, the first of the filename's trailing pair and in config_record "
                         "(e.g. LocalGP)")
    ap.add_argument("--author", required=True,
                    help="author string, the last of the filename's trailing pair and in config_record "
                         "(e.g. Giglio_etal2026)")
    ap.add_argument("--citation", required=True,
                    help="citation sentence; written to the top-level `citation` attr")
    ap.add_argument("--out", default=".")
    cfg = ap.parse_args()
    cfg.product_name = "".join(cfg.product_name.split())                  # filename tokens: whitespace-stripped,
    cfg.author = "".join(cfg.author.split())                    # case preserved, no other munging
    os.makedirs(cfg.out, exist_ok=True)
    for path in cfg.blobs:
        blob = xr.open_dataset(path)
        if "field" not in blob:
            raise SystemExit("%s carries no field; run ohc_derive with --quantities field" % path)
        dest = os.path.join(cfg.out, filename(quantity(blob)["name"], cfg.tag, _file_token(blob),
                                              cfg.product_name, cfg.author))
        out = build_dataset(blob, cfg.tag, cfg.provenance_link, cfg.citation, cfg.product_name)
        stamp_config_record(out, blob, cfg, path)                  # whole chain -> one config_record attr
        enc = {v: {"_FillValue": -999.0} for v in out.data_vars}   # target fill (NaN -> -999)
        enc["TIME"] = {"units": "days since 1900-01-01", "calendar": "proleptic_gregorian"}
        out.to_netcdf(dest, engine="netcdf4", encoding=enc)
        print("wrote", dest)


if __name__ == "__main__":
    main()
