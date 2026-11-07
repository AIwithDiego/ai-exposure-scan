#!/usr/bin/env bash
# Download this month's DB-IP "IP to Country Lite" database into data/geoip/.
# Run once at setup (and monthly if you want fresher data). Licence: CC BY 4.0, https://db-ip.com
set -euo pipefail
cd "$(dirname "$0")/.."
DIR=data/geoip
MONTH="${MONTH:-$(date -u +%Y-%m)}"
FILE="dbip-country-lite-$MONTH.csv.gz"
mkdir -p "$DIR"
trap 'rm -f "$DIR"/*.part' EXIT
if [ -s "$DIR/$FILE" ]; then
  echo "get-geoip: $DIR/$FILE already there"
  exit 0
fi
echo "get-geoip: downloading $FILE"
if ! curl -fsSL --retry 3 -o "$DIR/$FILE.part" "https://download.db-ip.com/free/$FILE"; then
  # Early in the month the new file may not be published yet: fall back to last month's.
  MONTH="$(date -u -d "$MONTH-01 -1 month" +%Y-%m)"
  FILE="dbip-country-lite-$MONTH.csv.gz"
  echo "get-geoip: not available yet, trying $FILE"
  curl -fsSL --retry 3 -o "$DIR/$FILE.part" "https://download.db-ip.com/free/$FILE"
fi
mv "$DIR/$FILE.part" "$DIR/$FILE"
echo "get-geoip: saved $DIR/$FILE (IP geolocation by DB-IP, CC BY 4.0)"
