"""DXT1 / DXT5 (BC1 / BC3) encoder and mipmaps in numpy, for textures made outside the game (2026-11-01). No Blender
and no external tool: images are uint8 arrays height x width x 4, top row first.

Colour blocks: the endpoints start on the block's principal axis and are refined by least squares on the chosen
indices, keeping the best fit per block. Alpha blocks use the block's min / max in the 8-value mode. Blocks are always
written in the 4-colour mode (colour 0 > colour 1), since DXT1's 3-colour mode means 1-bit alpha.
"""
import numpy as np

BATCH = 1 << 14        # blocks per pass: a palette distance table is (blocks, 16, 4, 3) floats
FIT_ROUNDS = 3
_WEIGHTS = np.array((1.0, 0.0, 2.0 / 3.0, 1.0 / 3.0), np.float32)   # index -> weight of colour 0


def nearest_power_of_two(n):
    low = 1
    while low * 2 <= n:
        low *= 2
    return low * 2 if n - low > low * 2 - n else low


def _resample(a, size, axis):
    """a float array resized along one axis: area average when shrinking, linear when growing"""
    n = a.shape[axis]
    if n == size:
        return a
    a = np.moveaxis(a, axis, 0)
    if size > n:
        x = (np.arange(size) + 0.5) * n / size - 0.5
        i = np.clip(np.floor(x).astype(int), 0, max(n - 2, 0))
        t = np.clip(x - i, 0.0, 1.0)[:, None, None]
        out = a[i] * (1.0 - t) + a[np.minimum(i + 1, n - 1)] * t
    else:
        total = np.concatenate((np.zeros_like(a[:1]), np.cumsum(a, axis=0)))
        edges = np.arange(size + 1) * n / size
        i = np.minimum(edges.astype(int), n - 1)
        t = (edges - i)[:, None, None]
        at_edges = total[i] * (1.0 - t) + total[i + 1] * t
        out = (at_edges[1:] - at_edges[:-1]) * size / n
    return np.moveaxis(out, 0, axis)


def resize(rgba, width, height):
    out = _resample(_resample(rgba.astype(np.float64), height, 0), width, 1)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def _renormalised(rgba):
    """rgb read as a unit vector again (averaged normals are shorter)"""
    v = rgba[..., :3].astype(np.float32) / 127.5 - 1.0
    length = np.sqrt((v * v).sum(-1, keepdims=True))
    v = np.where(length > 1e-5, v / np.maximum(length, 1e-5), np.array((0.0, 0.0, 1.0), np.float32))
    out = rgba.copy()
    out[..., :3] = np.clip(np.rint((v + 1.0) * 127.5), 0, 255).astype(np.uint8)
    return out


def mip_chain(rgba, normal=False):
    """[level 0, level 1 ... 1 x 1], each half the size of the last. normal: rgb holds a normal, kept unit length"""
    levels = [rgba]
    while max(levels[-1].shape[:2]) > 1:
        h, w = levels[-1].shape[:2]
        level = resize(levels[-1], max(1, w // 2), max(1, h // 2))
        levels.append(_renormalised(level) if normal else level)
    return levels


def _blocks(a):
    """an image as (blocks, 16, channels), pixels in row order; sizes that aren't multiples of 4 repeat their edge"""
    h, w = a.shape[:2]
    a = np.pad(a, ((0, -h % 4), (0, -w % 4), (0, 0)), mode="edge")
    h, w = a.shape[:2]
    return a.reshape(h // 4, 4, w // 4, 4, -1).transpose(0, 2, 1, 3, 4).reshape(-1, 16, a.shape[2])


def _to_565(c):
    return (np.clip(np.rint(c[:, 0] * 31.0 / 255.0), 0, 31).astype(np.uint32),
            np.clip(np.rint(c[:, 1] * 63.0 / 255.0), 0, 63).astype(np.uint32),
            np.clip(np.rint(c[:, 2] * 31.0 / 255.0), 0, 31).astype(np.uint32))


def _expand(r, g, b):
    return np.stack(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)), axis=1).astype(np.float32)


def _encode_colour(px):
    """(blocks, 16, 3) -> three arrays: colour 0, colour 1 (565) and the 32 index bits"""
    n = len(px)
    mean = px.mean(1)
    d = px - mean[:, None]
    cov = np.einsum("nij,nik->njk", d, d)
    cov /= np.maximum(np.trace(cov, axis1=1, axis2=2), 1.0)[:, None, None]   # keeps the iteration out of denormals
    axis = px.max(1) - px.min(1)
    axis[(axis == 0).all(1)] = 1.0
    for _ in range(4):
        axis = np.einsum("njk,nk->nj", cov, axis)
        length = np.sqrt((axis * axis).sum(1, keepdims=True))
        flat = length[:, 0] < 1e-6
        axis = axis / np.maximum(length, 1e-6)
        axis[flat] = 1.0
    t = (d * axis[:, None]).sum(2)
    c0, c1 = mean + axis * t.max(1, keepdims=True), mean + axis * t.min(1, keepdims=True)

    best_err = np.full(n, np.inf, np.float32)
    best_idx = np.zeros((n, 16), np.uint8)
    best0, best1 = np.zeros(n, np.uint32), np.zeros(n, np.uint32)
    for _ in range(FIT_ROUNDS):
        r0, g0, b0 = _to_565(c0)
        r1, g1, b1 = _to_565(c1)
        e0, e1 = _expand(r0, g0, b0), _expand(r1, g1, b1)
        palette = np.stack((e0, e1, (2.0 * e0 + e1) / 3.0, (e0 + 2.0 * e1) / 3.0), axis=1)
        dist = ((px[:, :, None, :] - palette[:, None, :, :]) ** 2).sum(3)
        idx = dist.argmin(2)
        err = dist.min(2).sum(1)
        better = err < best_err
        best_err[better] = err[better]
        best_idx[better] = idx[better]
        best0[better] = ((r0 << 11) | (g0 << 5) | b0)[better]
        best1[better] = ((r1 << 11) | (g1 << 5) | b1)[better]

        w = _WEIGHTS[idx]
        a2, b2, ab = (w * w).sum(1), ((1 - w) ** 2).sum(1), (w * (1 - w)).sum(1)
        ax, bx = (w[..., None] * px).sum(1), ((1 - w)[..., None] * px).sum(1)
        det = a2 * b2 - ab * ab
        ok = np.abs(det) > 1e-6
        safe = np.where(ok, det, 1.0)[:, None]
        c0 = np.where(ok[:, None], (b2[:, None] * ax - ab[:, None] * bx) / safe, c0)
        c1 = np.where(ok[:, None], (a2[:, None] * bx - ab[:, None] * ax) / safe, c1)

    swap = best0 < best1
    best0[swap], best1[swap] = best1[swap].copy(), best0[swap].copy()
    best_idx[swap] = np.array((1, 0, 3, 2), np.uint8)[best_idx[swap]]
    best_idx[best0 == best1] = 0
    bits = (best_idx.astype(np.uint32) << (2 * np.arange(16, dtype=np.uint32))).sum(1, dtype=np.uint32)
    return best0, best1, bits


def _encode_alpha(alpha):
    """(blocks, 16) uint8 -> two arrays: alpha 0, alpha 1, and (blocks, 6) bytes of 3-bit indices"""
    a0, a1 = alpha.max(1).astype(np.float32), alpha.min(1).astype(np.float32)
    steps = [a0, a1] + [((8 - i) * a0 + (i - 1) * a1) / 7.0 for i in range(2, 8)]
    palette = np.rint(np.stack(steps, axis=1))
    idx = np.abs(alpha[:, :, None].astype(np.float32) - palette[:, None, :]).argmin(2)
    bits = (idx.astype(np.uint64) << (3 * np.arange(16, dtype=np.uint64))).sum(1, dtype=np.uint64)
    packed = np.frombuffer(bits.astype("<u8").tobytes(), np.uint8).reshape(-1, 8)[:, :6]
    return a0.astype(np.uint8), a1.astype(np.uint8), packed


def encode(rgba, fourcc):
    """the blocks of one image, b"DXT1" (opaque: alpha is dropped) or b"DXT5" """
    blocks = _blocks(rgba)
    out = []
    for start in range(0, len(blocks), BATCH):
        part = blocks[start:start + BATCH]
        c0, c1, bits = _encode_colour(part[:, :, :3].astype(np.float32))
        colour = np.zeros(len(part), dtype=[("c0", "<u2"), ("c1", "<u2"), ("bits", "<u4")])
        colour["c0"], colour["c1"], colour["bits"] = c0, c1, bits
        if fourcc == b"DXT1":
            out.append(colour.tobytes())
            continue
        a0, a1, packed = _encode_alpha(part[:, :, 3])
        merged = np.zeros((len(part), 16), np.uint8)
        merged[:, 0], merged[:, 1], merged[:, 2:8] = a0, a1, packed
        merged[:, 8:16] = np.frombuffer(colour.tobytes(), np.uint8).reshape(-1, 8)
        out.append(merged.tobytes())
    return b"".join(out)
