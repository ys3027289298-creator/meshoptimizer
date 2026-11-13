#!/usr/bin/env bash
# End-to-end checks for EXT_texture_avif support in gltfpack.
# Usage: run_tests.sh [path-to-gltfpack]   (defaults to ../../build/cmake-full-av4/gltfpack)
set -u

cd "$(dirname "$0")"

GP="${1:-../../build/cmake-full-av4/gltfpack}"
OUT=run_out
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

python3 generate.py

# regenerate external/data-uri fixtures
python3 - <<'PY'
import struct, json, os, base64
gltf = {
    "asset": {"version": "2.0"},
    "extensionsUsed": ["EXT_texture_avif"], "extensionsRequired": ["EXT_texture_avif"],
    "samplers": [{"wrapS": 10497, "wrapT": 10497}],
    "images": [{"name": "red.avif", "uri": "red.avif"}],
    "textures": [{"sampler": 0, "extensions": {"EXT_texture_avif": {"source": 0}}}],
    "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
    "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
    "accessors": [{"componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]},
                  {"componentType": 5123, "count": 3, "type": "SCALAR"}],
    "buffers": [{"uri": "ext.bin", "byteLength": 30}],
    "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 24}, {"buffer": 0, "byteOffset": 24, "byteLength": 6}],
    "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0}
bin = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0) + struct.pack("<3H", 0, 1, 2)
os.makedirs("ext", exist_ok=True)
open("ext/ext.gltf", "w").write(json.dumps(gltf))
open("ext/red.avif", "wb").write(open("red.avif", "rb").read())
open("ext/ext.bin", "wb").write(bin)
g2 = json.loads(json.dumps(gltf))
g2["images"] = [{"name": "data.avif", "uri": "data:image/avif;base64," + base64.b64encode(open("red.avif", "rb").read()).decode()}]
g2["buffers"] = [{"byteLength": 30}]
os.makedirs("datauri", exist_ok=True)
open("datauri/datauri.gltf", "w").write(json.dumps(g2))
open("datauri/datauri.bin", "wb").write(bin)
PY

inspect()
{
	python3 - "$1" <<'PY'
import struct, json, sys
path = sys.argv[1]
d = open(path, "rb").read()
off = 12
gltf = bin = None
while off < len(d):
    ln, typ = struct.unpack("<II", d[off:off + 8])
    chunk = d[off + 8:off + 8 + ln]
    if typ == 0x4E4F534A:
        gltf = json.loads(chunk)
    else:
        bin = chunk
    off += 8 + ln
used = gltf.get("extensionsUsed", [])
textures = gltf.get("textures", [])
images = gltf.get("images", [])
payloads = []
for image in images:
    if "bufferView" in image:
        bv = gltf["bufferViews"][image["bufferView"]]
        payloads.append(bin[bv["byteOffset"]:bv["byteOffset"] + bv["byteLength"]])
print(json.dumps({"used": used, "required": gltf.get("extensionsRequired", []), "textures": textures,
                  "mimes": [i.get("mimeType") for i in images], "payloads": payloads,
                  "samplers": len(gltf.get("samplers", []))}, default=lambda x: list(x) if isinstance(x, (bytes, bytearray)) else str(x)))
PY
}

# --- raw preservation: AVIF bytes must be retained verbatim with the right extension wiring
"$GP" -i avif_only.glb -o "$OUT/only_raw.glb"
check "raw-only preserves avif bytes" "inspect '$OUT/only_raw.glb' | python3 -c 'import json,sys; d=json.load(sys.stdin); ref=list(open(\"red.avif\",\"rb\").read()); sys.exit(0 if d[\"mimes\"][0]==\"image/avif\" and d[\"payloads\"][0]==ref else 1)'"
check "raw-only writes EXT_texture_avif" "inspect '$OUT/only_raw.glb' | grep -q EXT_texture_avif"

"$GP" -i avif_fallback.glb -o "$OUT/fallback_raw.glb"
check "raw-fallback keeps source+avif" "inspect '$OUT/fallback_raw.glb' | grep -q '\"source\": 0' && inspect '$OUT/fallback_raw.glb' | grep -q EXT_texture_avif"

"$GP" -i avif_shared.glb -o "$OUT/shared_raw.glb"
check "raw-shared keeps two samplers and one avif image" "inspect '$OUT/shared_raw.glb' | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"samplers\"]==2 and d[\"mimes\"]==[\"image/avif\"] else 1)'"

"$GP" -i avif_mixed.glb -o "$OUT/mixed_raw.glb"
check "raw-mixed keeps avif and png" "inspect '$OUT/mixed_raw.glb' | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"mimes\"]==[\"image/avif\",\"image/png\"] else 1)'"

"$GP" -i avif_triple.glb -o "$OUT/triple_raw.glb"
check "raw-triple keeps source, webp and avif" "inspect '$OUT/triple_raw.glb' | python3 -c 'import json,sys; d=json.load(sys.stdin); ext=d[\"textures\"][0].get(\"extensions\",{}); sys.exit(0 if d[\"textures\"][0].get(\"source\")==0 and \"EXT_texture_webp\" in ext and \"EXT_texture_avif\" in ext else 1)'"
"$GP" -i avif_triple.glb -o "$OUT/triple_webp.glb" -tw
check "tw-triple collapses to webp only" "inspect '$OUT/triple_webp.glb' | python3 -c 'import json,sys; d=json.load(sys.stdin); ext=d[\"textures\"][0].get(\"extensions\",{}); sys.exit(0 if list(ext)==[\"EXT_texture_webp\"] and \"EXT_texture_avif\" not in d[\"used\"] else 1)'"

"$GP" -i ext/ext.gltf -o "$OUT/ext_raw.gltf"
check "raw-external writes .avif sidecar" "test -f '$OUT/red.avif' && cmp -s '$OUT/red.avif' red.avif"
"$GP" -i ext/ext.gltf -o "$OUT/ext_embed.glb"
check "raw-external glb embeds avif" "inspect '$OUT/ext_embed.glb' | grep -q image/avif"
"$GP" -i datauri/datauri.gltf -o "$OUT/datauri_raw.glb"
check "raw-datauri preserves avif" "inspect '$OUT/datauri_raw.glb' | grep -q image/avif"

# --- transcoding: AVIF must decode once and come out as WebP/KTX2 with the extension rewritten
"$GP" -i avif_only.glb -o "$OUT/only_webp.glb" -tw
check "tw emits webp and drops avif ext" "inspect '$OUT/only_webp.glb' | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"mimes\"][0]==\"image/webp\" and \"EXT_texture_avif\" not in d[\"used\"] and \"EXT_texture_webp\" in d[\"used\"] and bytes(d[\"payloads\"][0])[:4]==b\"RIFF\" else 1)'"

"$GP" -i avif_only.glb -o "$OUT/only_ktx2.glb" -tc
check "tc emits ktx2 and basisu ext" "inspect '$OUT/only_ktx2.glb' | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"mimes\"][0]==\"image/ktx2\" and \"KHR_texture_basisu\" in d[\"used\"] and \"EXT_texture_avif\" not in d[\"used\"] and bytes(d[\"payloads\"][0])[:4]==bytes([0xab,0x4b,0x54,0x58]) else 1)'"

"$GP" -i avif_only.glb -o "$OUT/only_uastc.glb" -tu
check "tu emits ktx2" "inspect '$OUT/only_uastc.glb' | grep -q image/ktx2"

"$GP" -i avif_mixed.glb -o "$OUT/mixed_webp.glb" -tw
check "tw mixed converts both images" "inspect '$OUT/mixed_webp.glb' | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if all(m==\"image/webp\" for m in d[\"mimes\"]) else 1)'"
"$GP" -i avif_shared.glb -o "$OUT/shared_ktx2.glb" -tc
check "tc shared keeps one image two samplers" "inspect '$OUT/shared_ktx2.glb' | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"samplers\"]==2 and d[\"mimes\"]==[\"image/ktx2\"] else 1)'"
"$GP" -i ext/ext.gltf -o "$OUT/ext_webp.gltf" -tw
check "tw external writes webp sidecar" "test -f '$OUT/red.webp'"

# --- diagnostics: malformed and oversized AVIF must not be silently dropped
"$GP" -i avif_corrupt.glb -o "$OUT/corrupt_raw.glb" 2>"$OUT/corrupt.log"
check "corrupt avif emits diagnostic" "grep -qi 'validating AVIF' '$OUT/corrupt.log'"
"$GP" -i avif_oversized.glb -o "$OUT/oversized_raw.glb" 2>"$OUT/oversized.log"
check "oversized avif emits diagnostic" "grep -qi 'validating AVIF' '$OUT/oversized.log'"
"$GP" -i avif_corrupt.glb -o "$OUT/corrupt_webp.glb" -tw 2>"$OUT/corrupt_tw.log"
check "corrupt avif transcode emits diagnostic" "grep -qi 'validating AVIF' '$OUT/corrupt_tw.log'"

# valid container but undecodable AV1 payload: raw preserves, transcode reports a decode error
"$GP" -i avif_badstream.glb -o "$OUT/badstream_raw.glb" 2>"$OUT/badstream_raw.log"
check "bad-bitstream avif is preserved in raw mode" "test -f '$OUT/badstream_raw.glb' && ! grep -qi 'validating AVIF' '$OUT/badstream_raw.log'"
"$GP" -i avif_badstream.glb -o "$OUT/badstream_webp.glb" -tw 2>"$OUT/badstream_tw.log"
check "bad-bitstream avif reports decode error on transcode" "grep -qi 'decoding AVIF' '$OUT/badstream_tw.log'"

# --- no temp files left behind
check "no temp files leaked" "test -z \"\$(ls /tmp/gltfpack-temp* 2>/dev/null)\""

echo "----------------------------------------"
if [ "$failures" -eq 0 ]; then
	echo "ALL AVIF TESTS PASSED"
else
	echo "$failures TEST(S) FAILED"
	exit 1
fi
