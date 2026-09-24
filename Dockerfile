FROM python:3.12-slim

# numpy is held below 2.5: 2.5 deprecated the array-shape assignment xarray's netCDF4 backend
# still uses, which warns on every .nc read/write. Lift the cap once xarray ships a 2.5-clean build.
# (The stock netCDF4/cftime wheels are built against numpy 1.x, so a single harmless "ndarray size
# changed" warning remains on import — off-the-shelf binaries, not worth a source build to silence.)
RUN pip install --no-cache-dir "numpy<2.5" "xarray>=2024.10" netCDF4 pytest

WORKDIR /app
