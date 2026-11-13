# AVIF texture tests for gltfpack

End-to-end coverage for `EXT_texture_avif` support. The fixtures are generated from scratch by
`generate.py`, which only needs Python 3 (standard library) and `ffmpeg` with `libaom-av1`.

## Generate fixtures

```
python3 generate.py
```

Produces self-contained `.glb` assets:

- `avif_only.glb` - required AVIF texture without a fallback image
- `avif_fallback.glb` - regular PNG `source` plus an `EXT_texture_avif` image
- `avif_shared.glb` - two textures with different samplers sharing one AVIF image
- `avif_mixed.glb` - one AVIF texture and one plain PNG texture
- `avif_corrupt.glb` - `image/avif` payload that is not a valid AVIF container
- `avif_badstream.glb` - valid AVIF boxes but an undecodable AV1 payload
- `avif_oversized.glb` - valid header advertising dimensions above the 16384 limit

## Run

```
# full build (with libavif): raw preservation, WebP/KTX2 transcoding, diagnostics
./run_tests.sh path/to/gltfpack

# build without libavif: preservation still works, transcoding must fail explicitly
./run_tests_nolibavif.sh path/to/gltfpack-without-libavif
```

The scripts regenerate fixtures every run and fail with a non-zero exit code on any mismatch.
