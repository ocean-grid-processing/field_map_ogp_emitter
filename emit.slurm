#!/bin/bash
#SBATCH --qos=preemptable
#SBATCH --export=NONE
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --time=00:30:00
#SBATCH --job-name=mld_emitter
#SBATCH --output=%x.%j.out
#SBATCH --mail-type=FAIL
#SBATCH --mail-user=katie.mills@colorado.edu
#SBATCH --mem=32GB
#SBATCH --exclude=blanca-g6-u21

module purge
module load anaconda/2023.09
conda activate ohc_crosscheck

cd $SLURM_SUBMIT_DIR
tag=TAG_TO_SET
product_name=LocalGP
author=Giglio_etal2026
citation="<citation sentence for the MLD product>"
results=/scratch/alpine/wimi7695/mld_prod/results_${tag}
# one blob: the identity level's derive output, derive_<tag>_<data>_tw<data>_<token>.nc
python emit.py \
  ${results}/derive_${tag}_*.nc \
  --tag ${tag} \
  --provenance-link https://github.com/ocean-grid-processing/provenance/blob/main/README.md \
  --code-version https://github.com/ocean-grid-processing/mld_emitter/commit/SHA_TO_SET \
  --product-name ${product_name} --author ${author} --citation "${citation}" \
  --out ${results}
