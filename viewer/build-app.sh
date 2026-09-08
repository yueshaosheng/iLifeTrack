#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
project_root=${script_dir:h}
app_bundle="$project_root/build/iLifeTrack.app"
installed_bundle="/Applications/iLifeTrack.app"
backend_dist="$project_root/build/backend-dist"
backend_work="$project_root/build/backend-work"
backend_spec="$project_root/build/backend-spec"
executable_dir="$app_bundle/Contents/MacOS"
resources_dir="$app_bundle/Contents/Resources"
agent_path="$HOME/Library/LaunchAgents/com.ilifetrack.app.plist"
agent_was_installed=false
signing_identity=${ILIFETRACK_CODESIGN_IDENTITY:-"iLifeTrack Local Signing"}

available_identities=$(security find-identity -v -p codesigning)
if [[ "$available_identities" != *"\"$signing_identity\""* ]]; then
    echo "找不到代码签名身份：$signing_identity" >&2
    echo "本机首次构建请先运行：$script_dir/setup-local-signing.sh" >&2
    exit 2
fi

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
    --name ilifetrack \
    --paths "$project_root/src" \
    --distpath "$backend_dist" \
    --workpath "$backend_work" \
    --specpath "$backend_spec" \
    --hidden-import keyring.backends.macOS \
    "$project_root/packaging/ilifetrack_backend.py"

rm -rf "$app_bundle"
mkdir -p "$executable_dir" "$resources_dir/backend"
install -m 755 "$script_dir/.build/release/iLifeTrack" "$executable_dir/iLifeTrack"
install -m 644 "$script_dir/Resources/Info.plist" "$app_bundle/Contents/Info.plist"
install -m 644 "$script_dir/Resources/AppIcon.icns" "$resources_dir/AppIcon.icns"
ditto "$backend_dist/ilifetrack" "$resources_dir/backend/ilifetrack"
codesign --force --sign "$signing_identity" \
    --identifier com.ilifetrack.background \
    "$resources_dir/backend/ilifetrack/ilifetrack"
codesign --force --deep --sign "$signing_identity" "$app_bundle"
codesign --verify --deep --strict "$app_bundle"

staged_bundle="/Applications/.iLifeTrack.app.staging"
rm -rf "$staged_bundle"
ditto "$app_bundle" "$staged_bundle"
rm -rf "$installed_bundle"
mv "$staged_bundle" "$installed_bundle"

if $agent_was_installed; then
    "$installed_bundle/Contents/Resources/backend/ilifetrack/ilifetrack" start >/dev/null
fi

echo "$installed_bundle"
