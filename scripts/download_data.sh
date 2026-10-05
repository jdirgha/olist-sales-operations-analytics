#!/usr/bin/env bash
# Download the Olist Brazilian E-Commerce dataset from Kaggle into data/raw/.
# Requires Kaggle credentials: ~/.kaggle/access_token or ~/.kaggle/kaggle.json (chmod 600).
# Raw files are made read-only afterwards so no step can modify them.
#
# Usage: scripts/download_data.sh [--force]

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAW_DIR="${PROJECT_ROOT}/data/raw"
KAGGLE_BIN="${PROJECT_ROOT}/.venv/bin/kaggle"
DATASET="olistbr/brazilian-ecommerce"

if [[ ! -x "${KAGGLE_BIN}" ]]; then
  echo "ERROR: Kaggle CLI not found at ${KAGGLE_BIN}. Run: .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -f "${HOME}/.kaggle/kaggle.json" && ! -f "${HOME}/.kaggle/access_token" \
      && -z "${KAGGLE_API_TOKEN:-}" && -z "${KAGGLE_USERNAME:-}" ]]; then
  echo "ERROR: No Kaggle credentials. Create a token at kaggle.com > Settings > API and save it to" >&2
  echo "       ~/.kaggle/access_token (new API token) or ~/.kaggle/kaggle.json (legacy key)." >&2
  exit 1
fi

shopt -s nullglob
existing=("${RAW_DIR}"/*.csv)
if (( ${#existing[@]} > 0 )) && [[ "${1:-}" != "--force" ]]; then
  echo "Raw data already present (${#existing[@]} CSV files). Use --force to re-download."
  exit 0
fi

mkdir -p "${RAW_DIR}"
chmod u+w "${RAW_DIR}"/*.csv 2>/dev/null || true

echo "Downloading ${DATASET} into ${RAW_DIR} ..."
"${KAGGLE_BIN}" datasets download "${DATASET}" -p "${RAW_DIR}" --unzip --force

chmod a-w "${RAW_DIR}"/*.csv
echo "Done. Files (read-only):"
ls -lh "${RAW_DIR}"/*.csv
