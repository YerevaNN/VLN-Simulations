#!/usr/bin/env bash
set -euo pipefail

VERSION=${VERSION:-v0.1.0}
ARCHIVE=natural-valley-v2-sample.tar.zst
SHA256=2b1e94d6a10439c60dd525fe80f642d34d4c940bc992adbfcb75d17811f46501
OUTPUT_ROOT=${1:-datasets}
URL="https://github.com/YerevaNN/VLN-Simulations/releases/download/$VERSION/$ARCHIVE"

mkdir -p "$OUTPUT_ROOT"
curl --fail --location --retry 5 --continue-at - --output "$OUTPUT_ROOT/$ARCHIVE" "$URL"
printf '%s  %s\n' "$SHA256" "$OUTPUT_ROOT/$ARCHIVE" | sha256sum --check --status
tar --use-compress-program=unzstd -xf "$OUTPUT_ROOT/$ARCHIVE" -C "$OUTPUT_ROOT"

echo "sample dataset: $OUTPUT_ROOT/natural-valley-v2"
