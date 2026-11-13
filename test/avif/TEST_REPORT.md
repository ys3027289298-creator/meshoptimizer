# AVIF support - test report

## Build matrix

All builds use the project's existing CMake/Make entry points.

| Build | Configure | Result |
| --- | --- | --- |
| No texture deps, `-Werror` | `cmake -S . -B build/cmake-werror -DMESHOPT_BUILD_GLTFPACK=ON -DMESHOPT_WERROR=ON` | OK, zero warnings |
| BasisU + libwebp (no libavif) | `cmake -S . -B build/cmake-noavif -DMESHOPT_BUILD_GLTFPACK=ON -DMESHOPT_GLTFPACK_BASISU_PATH=... -DMESHOPT_GLTFPACK_LIBWEBP_PATH=...` | OK, zero warnings |
| Full (BasisU + libwebp + libavif) | `cmake -S . -B build/cmake-full-av4 -DMESHOPT_BUILD_GLTFPACK=ON -DMESHOPT_GLTFPACK_BASISU_PATH=... -DMESHOPT_GLTFPACK_LIBWEBP_PATH=... -DMESHOPT_GLTFPACK_LIBAVIF_PATH=/tmp/libavif-static-install -DMESHOPT_GLTFPACK_LIBAVIF_EXTRA_LIBS=.../libaom.a` | OK, zero warnings |
| ASan + UBSan full | same as full plus `-DCMAKE_CXX_FLAGS=-fsanitize=address,undefined` | OK, zero warnings |
| Make full path | `make config=release gltfpack LIBAVIF=/tmp/libavif-static-install LIBAOM=/tmp/local/usr` | OK |
| Project demo tests | `make config=debug test` | OK |

## Functional tests

Commands (run from `test/avif`):

```
python3 generate.py
./run_tests.sh ../../build/cmake-full-av4/gltfpack
./run_tests_nolibavif.sh ../../build/cmake-noavif/gltfpack
```

Results:

- `run_tests.sh`: 22/22 PASS (raw preservation, external/data-URI, WebP `-tw`, KTX2 `-tc`/`-tu`,
  shared images, samplers, AVIF+PNG/KTX2/WebP combinations, a texture carrying `source` +
  `EXT_texture_webp` + `EXT_texture_avif` simultaneously, corrupt/oversized/bad-bitstream
  diagnostics, no temporary-file leaks).
- `run_tests_nolibavif.sh`: 6/6 PASS (raw preservation still works; `-tw`/`-tc` exit with code 3
  and an explicit "built without AVIF support" error, producing no output file).
- Same suite re-run against the ASan/UBSan binary: all PASS, no sanitizer reports.
- 12 additional malformed/truncated AVIF containers exercised under ASan: no crashes, every input
  either preserves cleanly or emits an `error validating AVIF image` diagnostic.
- Pixel round-trip: AVIF -> RGBA -> WebP decodes back to the expected color content and 8x8 size;
  KTX2 output starts with the valid `«KTX 20»` magic.

## Byte-level regression (non-AVIF assets)

A baseline binary was built from the unmodified HEAD (`git worktree /tmp/gltfpack-baseline HEAD`)
with the same BasisU/libwebp dependencies. Outputs were compared byte-for-byte across 22 scenarios
per input (`.glb` and `.obj`, modes `""`, `-cc`, `-noq`, `-tw`, `-tc`, `-tu`, `-c -cf`,
`-tc -ts 0.5 -tl 8`, `-tw -tq 5`, `-tu -tp`, `-tr`), including JSON `.gltf` output and `-r`
reports:

```
ALL 22 x2 NON-AVIF SCENARIOS BYTE-IDENTICAL
```

`gltfpack -test` log output is also identical between baseline and patched builds.

## Changed files

- `extern/cgltf.h` - parse/fixup `EXT_texture_avif` (`has_avif`, `avif_image`).
- `gltf/image.cpp` - `image/avif` MIME/extension, allocation-free ISO-BMFF box validation,
  `getDimensions`/`hasAlpha`/`validateAvif` (16384 dimension cap).
- `gltf/encodeavif.cpp` (new) - libavif decode to 8-bit RGBA and a dependency-free temporary PNG
  writer; per-image processing with RGBA/bitstream released before encoding.
- `gltf/encodebasis.cpp`, `gltf/encodewebp.cpp` - consume the AVIF temporary PNG; AVIF temp-file
  ownership kept in `prepareImagesAvif`.
- `gltf/material.cpp` - include `avif_image` in texture equality and image resolution.
- `gltf/write.cpp` - emit `EXT_texture_avif` on preserve; rewrite to `EXT_texture_webp`/
  `KHR_texture_basisu` on transcode.
- `gltf/gltfpack.cpp`, `gltf/gltfpack.h` - AVIF detection/validation, transcode orchestration,
  `extensionsUsed`/`extensionsRequired` rewrite, no-libavif error (exit 3).
- `CMakeLists.txt`, `Makefile` - optional `WITH_LIBAVIF` integration.
- `gltf/README.md` - user/build documentation.
- `test/avif/` - fixtures generator, shell test suites, docs.
