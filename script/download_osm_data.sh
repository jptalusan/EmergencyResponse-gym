#!/usr/bin/env bash

regiondetails="${1:-north-america/us/tennessee}"

curl -L -o "data/osm/osm_data.osm.pbf" "https://download.geofabrik.de/$regiondetails-latest.osm.pbf"
