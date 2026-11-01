"""Any Blender image -> the DDS the DMC4 shader reads (2026-11-01). Export only takes DDS images (`DDSHeader.from_bl_image`),
so a PNG / TGA / JPG in a material is converted into a packed DDS image, which then behaves like an imported texture.
The viewport shows what the game gets, compression included.

What each kind becomes follows the DX9 files (3,674 .tex under arctool):
- BASE: DXT1, or DXT5 when the alpha is used; `_BM`, revision 0x22.
- NORMAL: DXT5nm, X in alpha, Y in green, R and B 255 as in the game's maps (`_NM`, revision 0x32). Green is inverted
  from Blender's OpenGL convention: the shader's bitangent sign is sign(parallax_factor.z), 1 on new materials, so
  the display group flips it back (`Flip Normal Green`). `flip_green` is for maps already made the DirectX way.
- MASK: specular colour, DXT1 (`_MM`, revision 0x2). From a specular image, or 1 - roughness when there's none, or
  their product.
All have full mip chains, power-of-two sizes (3,668 of the files; other sizes are moved to the nearest) and a
colour range of 1 (`Tex112CustomProperties`). Revisions are set by `texture._new_tex_revision`, from the slot.

A converted image remembers how it was made (`albam_recipe` JSON, `albam_source_<n>` image pointers, which also keep the
sources from being purged): `refresh` runs the recipe again and only re-encodes when the result's pixels changed, so
repainting the source image and exporting is enough.
"""
import json
import re
import zlib

import bpy
import numpy as np

from albam.lib import dxt
from albam.lib.dds import DDSHeader

BASE, NORMAL, MASK = "BASE", "NORMAL", "MASK"
_KINDS = {BASE: ("_BM", "sRGB"), NORMAL: ("_NM", "Non-Color"), MASK: ("_MM", "Non-Color")}
SOCKET_KINDS = {"Diffuse BM": BASE, "Lightmap LM": BASE, "Normal NM": NORMAL, "Detail DNM": NORMAL,
                "Specular MM": MASK, "Alpha Mask AM": MASK, "Special Map": MASK}
MAX_SIZE = 4096        # the largest DX9 textures; larger ones are shrunk
RECIPE_PROP = "albam_recipe"
SOURCE_PROP = "albam_source_{}"
# alpha counts as used below this; alpha test / blending is told apart by the share of half-transparent pixels
OPAQUE_SHARE, BLEND_SHARE = 0.999, 0.5
_EXTENSIONS = re.compile(r"\.(png|jpe?g|tga|bmp|tiff?|exr|hdr|dds|webp)$", re.IGNORECASE)
_COPY_SUFFIX = re.compile(r"\.\d{3,}$")


def stem_of(name):
    """an image name as a file stem: no Blender .001 suffix, no extension, only characters safe in a game path"""
    stem = _EXTENSIONS.sub("", _COPY_SUFFIX.sub("", name))
    return re.sub(r"[^A-Za-z0-9_-]", "_", stem) or "texture"


def _linear_to_srgb(c):
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(np.maximum(c, 1e-8), 1 / 2.4) - 0.055)


def read_pixels(image):
    """uint8 height x width x 4, top row first, in the image's own encoding; None if it has no pixels to read"""
    if image.source not in ("FILE", "GENERATED"):
        return None
    w, h = image.size
    if not w or not h or not len(image.pixels):
        return None
    px = np.empty(w * h * 4, np.float32)
    image.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)[::-1]
    if image.is_float and image.colorspace_settings.name == "sRGB":   # float buffers are linear, byte ones as stored
        px = np.concatenate((_linear_to_srgb(px[..., :3]), px[..., 3:]), axis=2)
    return np.clip(np.rint(px * 255.0), 0, 255).astype(np.uint8)


def _channel(px, channel):
    """one channel, or the rgb average for None"""
    if channel is None:
        return px[..., :3].mean(2).astype(np.uint8)
    return px[..., channel]


def _game_size(px):
    h, w = px.shape[:2]
    size = min(dxt.nearest_power_of_two(w), MAX_SIZE), min(dxt.nearest_power_of_two(h), MAX_SIZE)
    return px if size == (w, h) else dxt.resize(px, *size)


def _fit(px, shape):
    return px if px.shape[:2] == shape[:2] else dxt.resize(px, shape[1], shape[0])


def _base_pixels(sources, channels, use_alpha):
    px = read_pixels(sources[0])
    if px is None:
        return None
    px = px.copy()
    alpha = sources[1] if len(sources) > 1 else None
    if alpha is not None:
        other = read_pixels(alpha)
        if other is not None:
            px[..., 3] = _channel(_fit(other, px.shape), channels[1])
    if not use_alpha:
        px[..., 3] = 255
    return px


def _normal_pixels(sources, flip_green):
    px = read_pixels(sources[0])
    if px is None:
        return None
    px = px.copy()
    if not flip_green:     # OpenGL (Blender) -> the game's green
        px[..., 1] = 255 - px[..., 1]
    px[..., 3] = 255
    return px


def _mask_pixels(sources, channels):
    specular = read_pixels(sources[0]) if sources[0] is not None else None
    roughness = read_pixels(sources[1]) if sources[1] is not None else None
    if specular is None and roughness is None:
        return None
    if specular is not None:
        rgb = specular[..., :3] if channels[0] is None else np.repeat(specular[..., channels[0]:channels[0] + 1], 3, axis=2)
    if roughness is not None:
        gloss = 255 - _channel(roughness if specular is None else _fit(roughness, specular.shape), channels[1])
        gloss = np.repeat(gloss[..., None], 3, axis=2)
        rgb = gloss if specular is None else (rgb.astype(np.uint16) * gloss // 255).astype(np.uint8)
    return np.concatenate((rgb, np.full(rgb.shape[:2] + (1,), 255, np.uint8)), axis=2)


def alpha_use(px):
    """how a base texture's alpha looks: NONE (opaque), TEST (cut-outs) or BLEND (mostly half transparent)"""
    alpha = px[..., 3]
    solid = (alpha > 239).mean()
    if solid >= OPAQUE_SHARE:
        return "NONE"
    return "BLEND" if 1.0 - solid - (alpha < 16).mean() > BLEND_SHARE else "TEST"


def _dds_bytes(px, kind):
    normal = kind == NORMAL
    fourcc = b"DXT1" if kind == MASK or (kind == BASE and px[..., 3].min() >= 250) else b"DXT5"
    levels = dxt.mip_chain(px, normal=normal)
    if normal:
        levels = [np.stack((np.full(lv.shape[:2], 255, np.uint8), lv[..., 1], np.full(lv.shape[:2], 255, np.uint8),
                            lv[..., 0]), axis=2) for lv in levels]
    h, w = px.shape[:2]
    header = DDSHeader(dwHeight=h, dwWidth=w, pixelfmt_dwFourCC=fourcc, dwMipMapCount=len(levels))
    header.set_constants()
    header.set_variables(compressed=True)
    return bytes(header) + b"".join(dxt.encode(level, fourcc) for level in levels)


def _make_image(name, px, kind):
    h, w = px.shape[:2]
    dds = _dds_bytes(px, kind)
    image = bpy.data.images.new(name, w, h)
    image.source = "FILE"
    image.pack(data=dds, data_len=len(dds))
    image.colorspace_settings.name = _KINDS[kind][1]
    return image


def _find(recipe, sources):
    for image in bpy.data.images:
        if image.get(RECIPE_PROP) and _same_recipe(json.loads(image[RECIPE_PROP]), recipe) and \
                [image.get(SOURCE_PROP.format(i)) for i in range(len(sources))] == sources:
            return image
    return None


def _same_recipe(a, b):
    return all(a.get(key) == b.get(key) for key in ("kind", "channels", "flip_green", "use_alpha"))


def convert(kind, sources, channels=None, flip_green=False, use_alpha=True):
    """(the DDS image, alpha_use) for `kind` from the source images: BASE [colour, optional alpha image], NORMAL
    [normal], MASK [specular or None, roughness or None]; channels: the channel to read from each, None = the image's
    colour (the alpha image's: its average). The same recipe gives back the same image, re-encoded only if the
    pixels changed. (None, None) if nothing could be read."""
    channels = list(channels or [None] * len(sources))
    if kind == BASE:
        px = _base_pixels(sources, channels, use_alpha)
    elif kind == NORMAL:
        px = _normal_pixels(sources, flip_green)
    else:
        px = _mask_pixels(sources, channels)
    if px is None:
        return None, None
    px = _game_size(px)
    crc = zlib.crc32(px.tobytes())
    use = alpha_use(px) if kind == BASE else "NONE"
    recipe = {"kind": kind, "channels": channels, "flip_green": flip_green, "use_alpha": use_alpha, "crc": crc}
    old = _find(recipe, sources)
    if old is not None and json.loads(old[RECIPE_PROP]).get("crc") == crc:
        return old, use
    first = next(s for s in sources if s is not None)
    stem = stem_of(first.name)
    suffix = _KINDS[kind][0]
    print(f"[Albam] converting {first.name} ({px.shape[1]} x {px.shape[0]}, {kind.lower()})")
    image = _make_image(f"{stem if stem.upper().endswith(suffix) else stem + suffix}.dds", px, kind)
    image[RECIPE_PROP] = json.dumps(recipe)
    for i, source in enumerate(sources):
        if source is not None:
            image[SOURCE_PROP.format(i)] = source
    if old is not None:
        asset, new_asset = old.albam_asset, image.albam_asset
        new_asset.app_id, new_asset.relative_path, new_asset.extension = asset.app_id, asset.relative_path, asset.extension
        name = old.name
        old.user_remap(image)
        bpy.data.images.remove(old)
        image.name = name
    return image, use


def solid_image(name, colour):
    """a base texture of one linear colour, for a material that has only a colour: the game has no flat colour input"""
    rgb = np.clip(_linear_to_srgb(np.array(colour[:3], np.float32)), 0.0, 1.0)
    px = np.empty((4, 4, 4), np.uint8)
    px[..., :3] = np.rint(rgb * 255.0)
    px[..., 3] = 255
    return _make_image(f"{stem_of(name)}_BM.dds", px, BASE)


def refresh(image):
    """a converted image brought up to date with its sources (the image itself if nothing changed)"""
    recipe = json.loads(image[RECIPE_PROP])
    count = len(recipe["channels"])
    sources = [image.get(SOURCE_PROP.format(i)) for i in range(count)]
    if not any(source is not None for source in sources):
        return image
    new, _use = convert(recipe["kind"], sources, recipe["channels"], recipe["flip_green"], recipe["use_alpha"])
    return new or image


def is_game_normal(image):
    """True for a normal map already in the game's layout (DXT5nm: red stays at 255)"""
    px = read_pixels(image)
    return px is not None and px[..., 0].mean() > 240 and px[..., 2].mean() > 240
