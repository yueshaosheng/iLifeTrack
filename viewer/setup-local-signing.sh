#!/bin/zsh
set -euo pipefail

identity_name="iLifeTrack Local Signing"
keychain_path=$(
    security default-keychain -d user \
        | tr -d '"' \
        | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
)

available_identities=$(security find-identity -v -p codesigning)
if [[ "$available_identities" == *"\"$identity_name\""* ]]; then
    echo "本地签名身份已存在：$identity_name"
    exit 0
fi

temporary_dir=$(mktemp -d /tmp/ilifetrack-signing.XXXXXX)
cleanup() {
    rm -rf -- "$temporary_dir"
}
trap cleanup EXIT

private_key="$temporary_dir/signing-key.pem"
certificate="$temporary_dir/signing-certificate.pem"
archive="$temporary_dir/signing-identity.p12"
archive_password="ilifetrack-local-import"

openssl req -new -newkey rsa:3072 -nodes -x509 -days 3650 \
    -subj "/CN=$identity_name/O=iLifeTrack" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=critical,digitalSignature" \
    -addext "extendedKeyUsage=critical,codeSigning" \
    -keyout "$private_key" \
    -out "$certificate" >/dev/null 2>&1
openssl pkcs12 -export -legacy \
    -inkey "$private_key" \
    -in "$certificate" \
    -name "$identity_name" \
    -passout "pass:$archive_password" \
    -out "$archive"

security import "$archive" \
    -k "$keychain_path" \
    -P "$archive_password" \
    -T /usr/bin/codesign >/dev/null
security add-trusted-cert \
    -r trustRoot \
    -p codeSign \
    -k "$keychain_path" \
    "$certificate"

available_identities=$(security find-identity -v -p codesigning)
if [[ "$available_identities" != *"\"$identity_name\""* ]]; then
    echo "本地签名身份创建失败。" >&2
    exit 2
fi

echo "已创建本地签名身份：$identity_name"
