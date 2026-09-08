#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
project_root=${script_dir:h}
app_bundle="$project_root/build/LifeTrack.app"
installed_bundle="/Applications/LifeTrack.app"
backend_dist="$project_root/build/backend-dist"
backend_work="$project_root/build/backend-work"
backend_spec="$project_root/build/backend-spec"
executable_dir="$app_bundle/Contents/MacOS"
resources_dir="$app_bundle/Contents/Resources"
agent_path="$HOME/Library/LaunchAgents/com.lifetrack.app.plist"
agent_was_installed=false

if [[ -f "$agent_path" ]]; then
    agent_was_installed=true
fi

swift build --package-path "$script_dir" -c release
"$script_dir/build-icon.sh" >/dev/null

rm -rf "$backend_dist" "$backend_work" "$backend_spec"
mkdir -p "$backend_dist" "$backend_work" "$backend_spec"
"$project_root/.venv/bin/pyinstaller" \
    --noconfirm \
    --onedir \
    --name lifetrack \
    --paths "$project_root/src" \
    --distpath "$backend_dist" \
    --workpath "$backend_work" \
    --specpath "$backend_spec" \
    --hidden-import keyring.backends.macOS \
    "$project_root/packaging/lifetrack_backend.py"

rm -rf "$app_bundle"
mkdir -p "$executable_dir" "$resources_dir/backend"
install -m 755 "$script_dir/.build/release/LifeTrack" "$executable_dir/LifeTrack"
install -m 644 "$script_dir/Resources/Info.plist" "$app_bundle/Contents/Info.plist"
install -m 644 "$script_dir/Resources/AppIcon.icns" "$resources_dir/AppIcon.icns"
ditto "$backend_dist/lifetrack" "$resources_dir/backend/lifetrack"
codesign --force --sign - \
    --identifier com.lifetrack.background \
    "$resources_dir/backend/lifetrack/lifetrack"
codesign --force --deep --sign - "$app_bundle"
codesign --verify --deep --strict "$app_bundle"

staged_bundle="/Applications/.LifeTrack.app.staging"
rm -rf "$staged_bundle"
ditto "$app_bundle" "$staged_bundle"
rm -rf "$installed_bundle"
mv "$staged_bundle" "$installed_bundle"

if $agent_was_installed; then
    "$installed_bundle/Contents/Resources/backend/lifetrack/lifetrack" start >/dev/null
fi

echo "$installed_bundle"
