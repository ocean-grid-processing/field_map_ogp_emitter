"""emit: the pass-through of the field, the ME4OH layout, the config_record consolidation, packaging."""
import json
import types

import numpy as np
import pytest
import xarray as xr

import emit


QUANTITY = {"name": "mld", "kind": "intensive", "units": "m", "long_name": "mixed layer depth",
            "scale_terms": {}, "publish_unit_factor": 1.0, "publish_units": "m"}


def _blob(with_sd=True):
    """A synthetic ohc_derive `field` blob: the published field (m) on a monthly grid, with its
    `field_sd` sibling and the attrs derive leaves (level, quantity, area_m2)."""
    time = np.array([np.datetime64("%d-07-01" % y) for y in (2005, 2006, 2007)])
    data = np.arange(3 * 2 * 2, dtype="float64").reshape(3, 2, 2)
    dv = {"field": (("time", "lat", "lon"), data)}
    if with_sd:
        dv["field_sd"] = (("time", "lat", "lon"), 0.1 * data)
    ds = xr.Dataset(dv, coords={"time": time, "lat": [10.0, 20.0], "lon": [0.0, 5.0]})
    for v in ds.data_vars:
        ds[v].attrs = {"field_units": "m", "reduction": "grid"}
    ds["lon"].attrs = {"units": "degrees_east"}
    ds["lat"].attrs = {"units": "degrees_north"}
    ds.attrs.update({"area_m2": 1e12, "level": "0_0", "quantity": json.dumps(QUANTITY)})
    return ds


def test_build_passes_the_field_through_unscaled():
    out = emit.build_dataset(_blob(), tag="dev", provenance_link=None)
    assert np.array_equal(out["mld"].values, _blob()["field"].transpose("lon", "lat", "time").values)
    assert out["mld"].attrs == {"units": "m", "long_name": "mixed layer depth"}


def test_me4oh_layout_and_coord_attrs():
    out = emit.build_dataset(_blob(), tag="dev", provenance_link=None)
    assert out["mld"].dims == ("LONGITUDE", "LATITUDE", "TIME")
    assert out["LONGITUDE"].attrs["units"] == "degrees_east"
    assert out["LATITUDE"].attrs["units"] == "degrees_north"


def test_sd_companion_present_and_unscaled():
    out = emit.build_dataset(_blob(), tag="dev", provenance_link=None)
    assert out["mld_std"].dims == ("LONGITUDE", "LATITUDE", "TIME")
    assert np.array_equal(out["mld_std"].values, _blob()["field_sd"].transpose("lon", "lat", "time").values)
    assert out["mld_std"].attrs["units"] == "m"


def test_mean_only_blob_has_no_sd():
    out = emit.build_dataset(_blob(with_sd=False), tag="dev", provenance_link=None)
    assert "mld_std" not in out.data_vars


def test_variable_names_follow_the_quantity():
    blob = _blob()
    blob.attrs["quantity"] = json.dumps(dict(QUANTITY, name="sst", long_name="sea surface temperature"))
    out = emit.build_dataset(blob, tag="dev", provenance_link=None)
    assert set(out.data_vars) == {"sst", "sst_std"}
    assert out["sst"].attrs["long_name"] == "sea surface temperature"


def test_blob_without_quantity_errors():
    blob = _blob()
    del blob.attrs["quantity"]
    with pytest.raises(SystemExit):
        emit.build_dataset(blob, tag="dev", provenance_link=None)


def test_axis_labels_and_provenance():
    out = emit.build_dataset(_blob(), tag="dev", provenance_link="http://p",
                             citation="Giglio et al. (2026), MLD map, DOI:...", product_name="LocalGP")
    assert out.attrs["level"] == "0_0"
    assert "time_window" not in out.attrs                                        # the field isn't referenced
    assert out.attrs["provenance_tag"] == "dev"
    assert out.attrs["provenance_link"] == "http://p"
    assert out.attrs["citation"] == "Giglio et al. (2026), MLD map, DOI:..."    # standalone top-level attr
    assert out.attrs["product_name"] == "LocalGP"                                # standalone top-level key


def test_filename():
    assert emit.filename("mld", "dev", "2005_2007", "LocalGP", "Giglio_etal2026") == \
        "mld_map_dev_2005_2007_LocalGP_Giglio_etal2026.nc"


def test_file_token_is_the_data_span():
    assert emit._file_token(_blob()) == "2005_2007"


def test_config_record_consolidates_chain_into_one_attr(tmp_path):
    blob = _blob()
    # the upstream chain as derive leaves it: localgp_* grouped by constituent, ohc_derive_* singletons
    blob.attrs.update({
        "localgp_ingest_run_config": json.dumps({"15_20":  {"var_name": "pt", "cp0": 3989.0, "dir_mean": "/a"},
                                                 "15_300": {"var_name": "pt", "cp0": 3989.0, "dir_mean": "/b"}}),
        "localgp_ingest_code_version": json.dumps({"15_20": "u", "15_300": "u"}),   # all agree
        "ohc_derive_run_config": json.dumps({"level": "0_0", "quantities": ["field"]}),
        "ohc_derive_run_facts": json.dumps({"level": "0_0", "constituents": ["15_20", "15_300"],
                                            "n_fac": {"15_20": 3, "15_300": 1}}),
        "ohc_derive_code_version": "https://github.com/argovis/ohc_derive/commit/dddd",
    })
    out = emit.build_dataset(blob, tag="M-260909", provenance_link="http://emit/docs",
                             citation="Giglio et al. (2026)")
    cfg = types.SimpleNamespace(
        blobs=["derive_x_0_0.nc"], tag="M-260909", provenance_link="http://emit/docs",
        code_version="https://github.com/argovis/field_map_ogp_emitter/commit/eeee", out=str(tmp_path),
        product_name="LocalGP", author="Giglio_etal2026", citation="Giglio et al. (2026)")
    emit.stamp_config_record(out, blob, cfg, "derive_x_0_0.nc")

    # ONE consolidated attribute, and none of the per-stage keys leaked out (keeps compact storage)
    assert "config_record" in out.attrs
    assert not any(k.endswith(("_run_config", "_run_facts", "_code_version")) for k in out.attrs)

    rec = json.loads(out.attrs["config_record"])
    assert set(rec) >= {"localgp_ingest", "ohc_derive", "field_map_ogp_emitter"}   # keyed by stage

    # forwarded ohc_derive block preserved; n_fac stays nested, never mistaken for a fan-out
    assert rec["ohc_derive"]["code_version"].endswith("dddd")
    assert rec["ohc_derive"]["run_facts"]["n_fac"] == {"15_20": 3, "15_300": 1}

    # per-constituent fan-out DRY'd into shared + per_constituent (lossless), scalar fan-out collapsed
    ig = rec["localgp_ingest"]["run_config"]
    assert ig["shared"] == {"cp0": 3989.0, "var_name": "pt"}
    assert ig["per_constituent"] == {"15_20": {"dir_mean": "/a"}, "15_300": {"dir_mean": "/b"}}
    assert rec["localgp_ingest"]["code_version"] == "u"

    # this step's own block
    assert rec["field_map_ogp_emitter"]["code_version"].endswith("eeee")
    assert rec["field_map_ogp_emitter"]["run_config"]["tag"] == "M-260909"
    assert rec["field_map_ogp_emitter"]["run_facts"]["level"] == "0_0"
    assert rec["field_map_ogp_emitter"]["run_facts"]["quantity"]["name"] == "mld"
    assert rec["field_map_ogp_emitter"]["run_facts"]["quantities_present"] == ["field"]
    assert rec["field_map_ogp_emitter"]["run_facts"]["ensemble"] is True

    # product_name/author ride in the config brick; citation does NOT (it has its own top-level attr)
    assert rec["field_map_ogp_emitter"]["run_config"]["product_name"] == "LocalGP"
    assert rec["field_map_ogp_emitter"]["run_config"]["author"] == "Giglio_etal2026"
    assert "citation" not in rec["field_map_ogp_emitter"]["run_config"]


def test_global_attrs_stay_compact():
    """<=8 global attrs keeps the file in HDF5 compact storage — level, provenance_tag, provenance_link,
    citation, product_name, config_record = 6 (plus _NCProperties on write = 7, under the ceiling)."""
    out = emit.build_dataset(_blob(), tag="dev", provenance_link="http://p",
                             citation="Giglio et al. (2026)", product_name="LocalGP")
    cfg = types.SimpleNamespace(blobs=["b.nc"], tag="dev", provenance_link="http://p",
                                code_version="http://c", out=".",
                                product_name="LocalGP", author="Giglio_etal2026", citation="Giglio et al. (2026)")
    emit.stamp_config_record(out, _blob(), cfg, "b.nc")
    assert len(out.attrs) <= 7          # 6 here; + _NCProperties on write = 7 < max_compact (compact)


def test_round_trip_through_files(tmp_path):
    src = str(tmp_path / "derive_dev_2005_2007_tw2005_2007_0_0.nc")
    _blob().to_netcdf(src)
    blob = xr.open_dataset(src)
    dest = str(tmp_path / emit.filename(emit.quantity(blob)["name"], "dev", emit._file_token(blob),
                                        "LocalGP", "Giglio_etal2026"))
    out = emit.build_dataset(blob, "dev", None, "Giglio et al. (2026)")
    emit.stamp_config_record(out, blob, types.SimpleNamespace(
        blobs=[src], tag="dev", provenance_link=None, code_version="http://c", out=str(tmp_path),
        product_name="LocalGP", author="Giglio_etal2026", citation="Giglio et al. (2026)"), src)
    enc = {v: {"_FillValue": -999.0} for v in out.data_vars}
    enc["TIME"] = {"units": "days since 1900-01-01", "calendar": "proleptic_gregorian"}
    out.to_netcdf(dest, engine="netcdf4", encoding=enc)
    assert xr.open_dataset(dest).attrs["citation"] == "Giglio et al. (2026)"   # round-trips

    back = xr.open_dataset(dest)
    assert "mld" in back.data_vars and "mld_std" in back.data_vars
    assert back["mld"].attrs["units"] == "m"
    assert back["mld"].dims == ("LONGITUDE", "LATITUDE", "TIME")
    assert np.issubdtype(back["TIME"].dtype, np.datetime64)          # days-since re-decoded on read
    assert back["TIME"].values[0] == np.datetime64("2005-07-01")
