#!/bin/bash
#SBATCH --qos=preemptable
#SBATCH --export=NONE
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --time=00:30:00
#SBATCH --job-name=field_map_ogp_emitter
#SBATCH --output=%x.%j.out
#SBATCH --mail-type=FAIL
#SBATCH --mail-user=katie.mills@colorado.edu
#SBATCH --mem=32GB
#SBATCH --exclude=blanca-g6-u21

module purge
module load anaconda/2023.09
conda activate ohc_crosscheck

cd $SLURM_SUBMIT_DIR
tag=260921-OP20260507
product_name=LocalGP
author=Giglio_etal2026
citation="Giglio, D. et al. (2026): LocalGP mixed layer depth. DOI: <fill in on deposit>."
results=/scratch/alpine/wimi7695/mld_post/results-260921
# one blob: the identity level's derive output, derive_<tag>_<data>_tw<data>_<token>.nc
python emit.py \
  ${results}/derive_${tag}_*.nc \
  --tag ${tag} \
  --provenance-link https://github.com/ocean-grid-processing/provenance/blob/main/README.md \
  --code-version https://github.com/ocean-grid-processing/field_map_ogp_emitter/releases/tag/1.1.0 \
  --product-name ${product_name} --author ${author} --citation "${citation}" \
  --out ${results}
