#!/usr/bin/env bash
set -euo pipefail

############################
# Defaults
############################
DEFAULT_INPUT="data/osm/osm_data.osm.pbf"
DEFAULT_OUTPUT="data/osmium/osm_data_extract.osm.pbf"
DEFAULT_BBOX="-180,-90,180,90" # Default bbox = whole world (you can tighten this if you want)

INPUT="${1:-$DEFAULT_INPUT}"
OUTPUT="${2:-$DEFAULT_OUTPUT}"
REGION="${3:-$DEFAULT_BBOX}"

############################
# 1. Check / install osmium-tool
############################
if ! command -v osmium >/dev/null 2>&1; then
  echo "osmium-tool not found. Attempting installation..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get updatezw
    sudo apt-get install -y osmium-tool
  elif command -v brew >/dev/null 2>&1; then
    brew install osmium-tool
  else
    echo "ERROR: No supported package manager found (apt-get or brew)."
    echo "Please install osmium-tool manually."
    exit 1
  fi
fi

############################
# 2. Validate input file
############################
if [[ ! -f "$INPUT" ]]; then
  echo "ERROR: Input PBF file not found: $INPUT"
  exit 1
fi

############################
# 3. Decide extraction mode (bbox vs polygon file)
############################
TMP_OUTPUT="${OUTPUT}.tmp.pbf"

rm -f "$TMP_OUTPUT"

if [[ -f "$REGION" ]]; then
  echo "Using polygon file: $REGION"
  osmium extract -p "$REGION" -o "$TMP_OUTPUT" "$INPUT"
else
  echo "Using bbox: $REGION"
  osmium extract --bbox "$REGION" -o "$TMP_OUTPUT" "$INPUT"
fi

############################
# 4. Check if extraction produced meaningful output
############################
if [[ ! -f "$TMP_OUTPUT" ]]; then
  echo "No output generated. Copying original file."
  cp "$INPUT" "$OUTPUT"
  exit 0
fi

INPUT_SIZE=$(stat -c%s "$INPUT" 2>/dev/null || wc -c < "$INPUT")
OUTPUT_SIZE=$(stat -c%s "$TMP_OUTPUT" 2>/dev/null || wc -c < "$TMP_OUTPUT")

# If extraction is empty or identical size, assume region not present
if [[ "$OUTPUT_SIZE" -eq 0 || "$OUTPUT_SIZE" -eq "$INPUT_SIZE" ]]; then
  echo "Region not found or empty result. Copying original file."
  cp "$INPUT" "$OUTPUT"
  rm -f "$TMP_OUTPUT"
else
  mv "$TMP_OUTPUT" "$OUTPUT"
  echo "Extraction successful: $OUTPUT"
fi
