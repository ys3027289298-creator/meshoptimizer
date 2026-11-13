#!/usr/bin/env python3
"""Generate AVIF glTF test assets for gltfpack.

The generator only relies on the Python standard library and ffmpeg (for AVIF encoding);
the produced .glb files embed all images as buffer views so that the assets are self-contained.

Assets:
  avif_only.glb      single material, EXT_texture_avif without a PNG fallback (extensionsRequired)
  avif_fallback.glb  EXT_texture_avif plus a regular PNG source fallback
  avif_shared.glb    two textures sharing one AVIF image, with distinct samplers
  avif_mixed.glb     one AVIF texture and one PNG texture in the same asset
  avif_triple.glb    one texture carrying source + EXT_texture_webp + EXT_texture_avif together
  avif_corrupt.glb     an image/avif buffer view whose payload is not a valid AVIF container
  avif_badstream.glb   valid AVIF boxes (passes container checks) but an undecodable AV1 payload
  avif_oversized.glb   structurally valid AVIF header advertising dimensions above the limit
"""

import json
import os
import struct
import subprocess
import sys
import zlib


def write_png(path, width, height, rgba):
    """rgba: flat list of width*height (r, g, b, a) tuples."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (none)
        for x in range(width):
            raw.extend(rgba[y * width + x])

    def chunk(tag, payload):
        out = struct.pack(">I", len(payload)) + tag + payload
        out += struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        return out

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(data)


def encode_avif(src_png, dst_avif):
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        src_png,
        "-frames:v",
        "1",
        "-c:v",
        "libaom-av1",
        "-still-picture",
        "1",
        dst_avif,
    ]
    subprocess.check_call(cmd)


def box(box_type, payload):
    return struct.pack(">I", 8 + len(payload)) + box_type.encode("ascii") + payload


def make_oversized_avif():
    """A structurally valid AVIF container whose ispe box exceeds gltfpack's dimension limit."""
    ftyp = box("ftyp", b"avif" + struct.pack(">I", 0) + b"avif" + b"mif1" + b"miaf")
    ispe = struct.pack(">I", 0) + struct.pack(">II", 32768, 16)  # version/flags, width, height
    ipco = box("ipco", box("ispe", ispe))
    iprp = box("iprp", ipco)
    meta = box("meta", struct.pack(">I", 0) + iprp)  # full box header
    return ftyp + meta


class GlbBuilder:
    def __init__(self):
        self.buffer = bytearray()
        self.buffer_views = []
        self.images = []
        self.textures = []
        self.samplers = []
        self.materials = []
        self.extensions_used = []
        self.extensions_required = []

    def add_view(self, data):
        while len(self.buffer) % 4:
            self.buffer.append(0)
        offset = len(self.buffer)
        self.buffer.extend(data)
        index = len(self.buffer_views)
        self.buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data)})
        return index

    def add_image(self, name, data, mime):
        view = self.add_view(data)
        index = len(self.images)
        self.images.append({"name": name, "bufferView": view, "mimeType": mime})
        return index

    def add_sampler(self, mag, minf, wrap_s, wrap_t):
        index = len(self.samplers)
        self.samplers.append({"magFilter": mag, "minFilter": minf, "wrapS": wrap_s, "wrapT": wrap_t})
        return index

    def add_texture(self, name, sampler, source=None, basisu=None, webp=None, avif=None):
        index = len(self.textures)
        texture = {"name": name, "sampler": sampler}
        if source is not None:
            texture["source"] = source
        extensions = {}
        if basisu is not None:
            extensions["KHR_texture_basisu"] = {"source": basisu}
        if webp is not None:
            extensions["EXT_texture_webp"] = {"source": webp}
        if avif is not None:
            extensions["EXT_texture_avif"] = {"source": avif}
        if extensions:
            texture["extensions"] = extensions
        self.textures.append(texture)
        return index

    def add_material(self, name, texture):
        index = len(self.materials)
        self.materials.append(
            {
                "name": name,
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": texture},
                    "metallicFactor": 0,
                    "roughnessFactor": 1,
                },
            }
        )
        return index

    def use(self, ext, required=False):
        if ext not in self.extensions_used:
            self.extensions_used.append(ext)
        if required and ext not in self.extensions_required:
            self.extensions_required.append(ext)

    def write(self, path):
        # a trivial triangle mesh so that the asset has valid geometry references
        positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
        pos_view = self.add_view(positions)
        indices = struct.pack("<3H", 0, 1, 2)
        idx_view = self.add_view(indices)

        gltf = {
            "asset": {"version": "2.0", "generator": "gltfpack avif test generator"},
            "extensionsUsed": self.extensions_used,
            "extensionsRequired": self.extensions_required,
            "samplers": self.samplers,
            "images": self.images,
            "textures": self.textures,
            "materials": self.materials,
            "buffers": [{"byteLength": len(self.buffer)}],
            "bufferViews": self.buffer_views,
            "accessors": [
                {"bufferView": pos_view, "componentType": 5126, "count": 3, "type": "VEC3",
                 "min": [0, 0, 0], "max": [1, 1, 0]},
                {"bufferView": idx_view, "componentType": 5123, "count": 3, "type": "SCALAR"},
            ],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0, "mode": 4}]}],
            "nodes": [{"mesh": 0}],
            "scenes": [{"nodes": [0]}],
            "scene": 0,
        }

        json_data = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
        while len(json_data) % 4:
            json_data += b" "
        while len(self.buffer) % 4:
            self.buffer.append(0)

        total = 12 + 8 + len(json_data) + 8 + len(self.buffer)
        out = struct.pack("<III", 0x46546C67, 2, total)
        out += struct.pack("<II", len(json_data), 0x4E4F534A) + json_data
        out += struct.pack("<II", len(self.buffer), 0x004E4942) + bytes(self.buffer)
        with open(path, "wb") as f:
            f.write(out)


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))

    red = [(220, 60, 60, 255)] * (8 * 8)
    blue = [(60, 80, 220, 255)] * (8 * 8)
    green = [(60, 200, 90, 128)] * (8 * 8)  # partial alpha

    png_red = os.path.join(out_dir, "red.png")
    png_blue = os.path.join(out_dir, "blue.png")
    avif_red = os.path.join(out_dir, "red.avif")
    avif_blue = os.path.join(out_dir, "blue.avif")
    avif_green = os.path.join(out_dir, "green.avif")

    write_png(png_red, 8, 8, red)
    write_png(png_blue, 8, 8, blue)
    write_png(os.path.join(out_dir, "green.png"), 8, 8, green)
    encode_avif(png_red, avif_red)
    encode_avif(png_blue, avif_blue)
    encode_avif(os.path.join(out_dir, "green.png"), avif_green)

    red_avif = open(avif_red, "rb").read()
    blue_avif = open(avif_blue, "rb").read()
    green_avif = open(avif_green, "rb").read()
    red_png = open(png_red, "rb").read()

    repeat = 9785
    wrap = 10497
    linear_mip = 9987

    # avif_only.glb: required AVIF texture, no fallback
    b = GlbBuilder()
    sampler = b.add_sampler(9729, linear_mip, repeat, repeat)
    image = b.add_image("red.avif", red_avif, "image/avif")
    texture = b.add_texture("avif_only", sampler, avif=image)
    b.add_material("avif_only", texture)
    b.use("EXT_texture_avif", required=True)
    b.write(os.path.join(out_dir, "avif_only.glb"))

    # avif_fallback.glb: PNG source + AVIF extension on the same texture
    b = GlbBuilder()
    sampler = b.add_sampler(9729, linear_mip, repeat, repeat)
    png_image = b.add_image("red.png", red_png, "image/png")
    avif_image = b.add_image("red.avif", red_avif, "image/avif")
    texture = b.add_texture("avif_fallback", sampler, source=png_image, avif=avif_image)
    b.add_material("avif_fallback", texture)
    b.use("EXT_texture_avif")
    b.write(os.path.join(out_dir, "avif_fallback.glb"))

    # avif_shared.glb: two textures (different samplers) reference the same AVIF image
    b = GlbBuilder()
    sampler_a = b.add_sampler(9729, linear_mip, repeat, repeat)
    sampler_b = b.add_sampler(9728, 9986, wrap, wrap)
    image = b.add_image("blue.avif", blue_avif, "image/avif")
    texture_a = b.add_texture("shared_repeat", sampler_a, avif=image)
    texture_b = b.add_texture("shared_clamp", sampler_b, avif=image)
    b.add_material("shared_a", texture_a)
    b.add_material("shared_b", texture_b)
    b.use("EXT_texture_avif", required=True)
    b.write(os.path.join(out_dir, "avif_shared.glb"))

    # avif_mixed.glb: one AVIF texture and one plain PNG texture
    b = GlbBuilder()
    sampler = b.add_sampler(9729, linear_mip, repeat, repeat)
    avif_image = b.add_image("green.avif", green_avif, "image/avif")
    png_image = b.add_image("red.png", red_png, "image/png")
    texture_avif = b.add_texture("avif_tex", sampler, avif=avif_image)
    texture_png = b.add_texture("png_tex", sampler, source=png_image)
    b.add_material("with_avif", texture_avif)
    b.add_material("with_png", texture_png)
    b.use("EXT_texture_avif", required=True)
    b.write(os.path.join(out_dir, "avif_mixed.glb"))

    # avif_triple.glb: a regular PNG source plus webp and avif extension images on one texture;
    # raw mode must retain all three references
    webp_placeholder = b"RIFF" + struct.pack("<I", 24) + b"WEBP" + b"VP8 " + b"\x00" * 12
    b = GlbBuilder()
    sampler = b.add_sampler(9729, linear_mip, repeat, repeat)
    png_image = b.add_image("red.png", red_png, "image/png")
    webp_image = b.add_image("red.webp", webp_placeholder, "image/webp")
    avif_image = b.add_image("red.avif", red_avif, "image/avif")
    texture = b.add_texture("triple", sampler, source=png_image, webp=webp_image, avif=avif_image)
    b.add_material("triple", texture)
    b.use("EXT_texture_webp")
    b.use("EXT_texture_avif", required=True)
    b.write(os.path.join(out_dir, "avif_triple.glb"))

    # avif_corrupt.glb: declared image/avif with a payload that fails container validation
    b = GlbBuilder()
    sampler = b.add_sampler(9729, linear_mip, repeat, repeat)
    image = b.add_image("broken.avif", b"NOT_AN_AVIF_CONTAINER" + b"\x00" * 32, "image/avif")
    texture = b.add_texture("corrupt", sampler, avif=image)
    b.add_material("corrupt", texture)
    b.use("EXT_texture_avif", required=True)
    b.write(os.path.join(out_dir, "avif_corrupt.glb"))

    # avif_badstream.glb: structurally valid container so it survives raw mode, but the mdat
    # payload is not an AV1 bitstream; libavif decoding (transcode) must report a clear error
    ftyp = box("ftyp", b"avif" + struct.pack(">I", 0) + b"avif" + b"mif1")
    ispe = struct.pack(">I", 0) + struct.pack(">II", 8, 8)
    ipco = box("ipco", box("ispe", ispe))
    iprp = box("iprp", ipco)
    meta = box("meta", struct.pack(">I", 0) + iprp)
    bad_stream = ftyp + meta + box("mdat", b"\x00" * 64)
    b = GlbBuilder()
    sampler = b.add_sampler(9729, linear_mip, repeat, repeat)
    image = b.add_image("badstream.avif", bad_stream, "image/avif")
    texture = b.add_texture("badstream", sampler, avif=image)
    b.add_material("badstream", texture)
    b.use("EXT_texture_avif", required=True)
    b.write(os.path.join(out_dir, "avif_badstream.glb"))

    # avif_oversized.glb: valid AVIF boxes, ispe dimension above the 16384 limit
    b = GlbBuilder()
    sampler = b.add_sampler(9729, linear_mip, repeat, repeat)
    image = b.add_image("oversized.avif", make_oversized_avif(), "image/avif")
    texture = b.add_texture("oversized", sampler, avif=image)
    b.add_material("oversized", texture)
    b.use("EXT_texture_avif", required=True)
    b.write(os.path.join(out_dir, "avif_oversized.glb"))

    print("generated:", ", ".join(sorted(f for f in os.listdir(out_dir) if f.endswith(".glb"))))


if __name__ == "__main__":
    sys.exit(main())
