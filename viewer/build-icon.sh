#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
resources_dir="$script_dir/Resources"
source_png="$resources_dir/AppIcon.png"
iconset="$script_dir/.build/AppIcon.iconset"
output="$resources_dir/AppIcon.icns"

if [[ ! -f "$source_png" ]]; then
    echo "找不到 AppIcon.png" >&2
    exit 2
fi

rm -rf "$iconset"
mkdir -p "$iconset"

for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$source_png" \
        --out "$iconset/icon_${size}x${size}.png" >/dev/null
    doubled=$((size * 2))
    sips -z "$doubled" "$doubled" "$source_png" \
        --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns "$iconset" -o "$output"
echo "$output"
