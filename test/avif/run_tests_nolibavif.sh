#!/usr/bin/env bash
# Checks for a gltfpack binary built WITHOUT libavif: the build must exist, raw AVIF preservation
# must keep working, and any transcode request must fail with a clear diagnostic instead of
# silently dropping the texture.
# Usage: run_tests_nolibavif.sh [path-to-gltfpack-without-libavif]
set -u

cd "$(dirname "$0")"

GP="${1:-../../build/cmake-werror/gltfpack}"
OUT=run_out_nolibavif
mkdir -p "$OUT"

failures=0
check()
{
	local name="$1" condition="$2"
	if eval "$condition"; then
		echo "PASS $name"
	else
		echo "FAIL $name"
		failures=$((failures + 1))
	fi
}

python3 generate.py >/dev/null

"$GP" -i avif_only.glb -o "$OUT/raw.glb" 2>"$OUT/raw.log"
check "raw AVIF preservation works without libavif" "test -f '$OUT/raw.glb'"
check "raw run is silent about AVIF support" "! grep -qi 'without AVIF support' '$OUT/raw.log'"

"$GP" -i avif_only.glb -o "$OUT/tw.glb" -tw 2>"$OUT/tw.log"
check "-tw fails clearly without libavif" "test ! -f '$OUT/tw.glb' && grep -qi 'without AVIF support' '$OUT/tw.log'"

"$GP" -i avif_only.glb -o "$OUT/tc.glb" -tc 2>"$OUT/tc.log"
check "-tc fails clearly without libavif" "test ! -f '$OUT/tc.glb' && grep -qi 'without AVIF support' '$OUT/tc.log'"

"$GP" -i avif_mixed.glb -o "$OUT/mixed_tw.glb" -tw 2>"$OUT/mixed.log"
check "mixed asset also refuses partial transcode" "test ! -f '$OUT/mixed_tw.glb' && grep -qi 'without AVIF support' '$OUT/mixed.log'"

echo "----------------------------------------"
if [ "$failures" -eq 0 ]; then
	echo "ALL NO-LIBAVIF TESTS PASSED"
else
	echo "$failures TEST(S) FAILED"
	exit 1
fi
