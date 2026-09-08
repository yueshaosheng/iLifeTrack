#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
resources_dir="$script_dir/Resources"
source_svg="$resources_dir/AppIcon.svg"
master_dir="$script_dir/.build/icon-master"
iconset="$script_dir/.build/AppIcon.iconset"
output="$resources_dir/AppIcon.icns"

rm -rf "$master_dir" "$iconset"
mkdir -p "$master_dir" "$iconset"
qlmanage -t -s 1024 -o "$master_dir" "$source_svg" >/dev/null 2>&1
master_png="$master_dir/AppIcon.svg.png"

if [[ ! -f "$master_png" ]]; then
    echo "无法从 AppIcon.svg 生成图标" >&2
    exit 2
fi

for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$master_png" \
        --out "$iconset/icon_${size}x${size}.png" >/dev/null
    doubled=$((size * 2))
    sips -z "$doubled" "$doubled" "$master_png" \
        --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns "$iconset" -o "$output"
echo "$output"
