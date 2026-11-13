"""PBR materials for dmc4_hook's PbrMaterials (2026-11-15; plan and shader: Vibed\\PBR\\README.md, the format is the
header comment of D:\\dmc4_hook\\src\\dev\\pbr\\material_pbr.inc, owned by the shader).

PbrMaterials replaces the pixel shaders of XfMaterialStandard's lit SPECULAR_RIM keys, which no game file uses, with a
GGX metal / roughness shader. So a material is PBR when its Specular function is RIM (0x4); nothing else is stored:
- envmap_bias 5 (the environment cube's last mip = roughness 1);
- fresnel_factor = (roughness scale, metal scale, dielectric F0, reflection strength). Roughness = mask G x x, metal =
  mask B x y, occlusion = mask R; with no mask the engine binds NullWhite (ORM = 1), so x / y are the values. F0 0.04
  is Blender's Specular IOR Level 0.5 (F0 = level x 0.08). Reflection strength scales only the reflections (the
  stage's ambient light read in the reflection direction by default): 1 = physically right, 0 = none; highlights from
  lights don't use it;
- subsurface scattering = lighting THINSH4SPOT (0x4): lightmap_factor rgb = the scatter colour (per channel how far
  light spreads past the shadow line, 0..1, and the colour of light coming through; skin ~ (0.5, 0.2, 0.12)); the
  additional map R = thickness (0 thin: light comes through .. 1 thick), G = where it scatters. No additional map =
  NullWhite: scatters everywhere, transmits nowhere. EMITSH4SPOT keeps its stock meaning (additional R = emission x
  lightmap_factor), so a material has SSS or emission, not both;
- the mask and additional map are read with the normal map's UV, as in the stock shaders.

Only the keys in PBR_KEYS have a replaced shader (generated from XfMaterialStandard.bfx's permutation table at 0x56C
with Vibed\\PBR\\check_shader.py's rule: specular 4, lighting 1-4, normal map NONE / STANDARD, lightmap NONE /
STANDARD / SHADOW / VCOLOR, multitexture NONE, key present: 70 keys, 28 pixel shaders). Any other RIM key draws the
game's stock rim shader, so export refuses it (`material.check_material_153`).
"""
import math

import bpy

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry

APP_ID = "dmc4"
RIM = "0x4"
ENV_BIAS = 5
DEFAULT_F0 = 0.04          # Blender's Specular IOR Level 0.5
F0_PER_LEVEL = 0.08        # F0 = Specular IOR Level x 0.08
DEFAULT_REFLECTION = 1.0
SCATTER_PER_WEIGHT = 0.5   # Principled Subsurface Weight 1 -> the widest channel scatters 0.5
DEFAULT_LIGHTMAP_FACTOR = (1.0, 1.0, 1.0, 0.0)
SH4SPOT, THIN, EMIT = "0x2", "0x4", "0x3"
FUNC_RADIX = (("func_skin", 7), ("func_lighting", 5), ("func_normalmap", 4), ("func_specular", 5),
              ("func_lightmap", 8), ("func_multitexture", 7))
PBR_KEYS = frozenset((
    567, 574, 575, 576, 577, 578, 579, 580, 581, 582, 583, 584, 585, 586, 587, 588, 589, 590, 591, 592, 593, 594, 602,
    609, 610, 611, 612, 613, 614, 615, 616, 617, 618, 619, 620, 621, 622, 623, 624, 625, 626, 627, 628, 629, 1267, 1281,
    1288, 1302, 1316, 1323, 1967, 1981, 1988, 2002, 2016, 2023, 4067, 4075, 4076, 4077, 4080, 4081, 4088, 4102, 4110,
    4111, 4112, 4115, 4116, 4123))
GROUP_NODE = "MTFrameworkGroup"
MASK_SOCKET, ADDITIONAL_SOCKET = "Specular MM", "Alpha Mask AM"


def _int(value):
    return int(value, 16) if isinstance(value, str) else int(value)


def key_of(functions):
    """the shader key (pipeline) of func values given as {name: int or hex string}"""
    key, place = 0, 1
    for name, radix in FUNC_RADIX:
        key += _int(functions[name]) * place
        place *= radix
    return key


def functions_of(props, **override):
    """the material's func values (ints), some replaced"""
    values = {name: _int(getattr(props, name)) for name, _radix in FUNC_RADIX}
    values.update({k: _int(v) for k, v in override.items()})
    return values


def supported(functions):
    """True if dmc4_hook replaces this key's pixel shader when its specular is RIM"""
    return key_of(dict(functions, func_specular=4)) in PBR_KEYS


def unsupported_reason(functions):
    """why a RIM key has no PBR shader, in words (None if it has one)"""
    f = dict(functions, func_specular=4)
    if key_of(f) in PBR_KEYS:
        return None
    if f["func_lighting"] == 0:
        return "unlit materials (lighting NONE) have no PBR shader"
    if f["func_multitexture"] != 0:
        return "a multitexture function other than NONE has no PBR shader"
    if f["func_normalmap"] > 1:
        return "only normal map NONE / STANDARD have a PBR shader"
    if f["func_lightmap"] not in (0, 1, 2, 5):
        return "only lightmap NONE / STANDARD / SHADOW / VCOLOR have a PBR shader"
    return "this combination of skin, lighting and lightmap has no PBR shader"


def props_of(mat):
    return mat.albam_custom_properties.get_custom_properties_for_appid(APP_ID)


def is_pbr(mat):
    try:
        return props_of(mat).func_specular == RIM
    except Exception:
        return False


def scatter_from_principled(weight, radius):
    """the scatter colour (0..1 per channel) for a Principled Subsurface Weight and Radius"""
    top = max(radius) if max(radius) > 0 else 1.0
    return tuple(min(max(weight * r / top * SCATTER_PER_WEIGHT, 0.0), 1.0) for r in radius)


def principled_from_scatter(scatter):
    """(Subsurface Weight, Radius) for the Blender preview of a scatter colour"""
    top = max(scatter)
    if top <= 0:
        return 0.0, (1.0, 1.0, 1.0)
    return min(top / SCATTER_PER_WEIGHT, 1.0), tuple(c / top for c in scatter)


def roughness_from_power(power):
    """the Blinn-Phong SpecularPow of a classic material as a GGX roughness (the import display's mapping)"""
    return math.sqrt(2.0 / (power + 2.0)) if power > 0 else 1.0


def power_from_roughness(roughness):
    return min(max(2.0 / max(roughness, 0.01) ** 2 - 2.0, 1.0), 100.0)


def _group(mat):
    return mat.node_tree.nodes.get(GROUP_NODE) if mat.node_tree else None


def _socket(group, name):
    return group.inputs.get(name) if group is not None else None


def update_display(mat):
    """the MT Framework group's PBR inputs from the material's values (nothing for a classic material but PBR off)"""
    group = _group(mat)
    if group is None:
        return
    if _socket(group, "PBR") is None:   # a group saved before PBR materials: add the inputs
        from .material import _create_mtfw_shader
        _create_mtfw_shader()
        if _socket(group, "PBR") is None:
            return
    props = props_of(mat)
    pbr = props.func_specular == RIM
    group.inputs["PBR"].default_value = 1 if pbr else 0
    if not pbr:
        group.inputs["Subsurface DMC4"].default_value = 0.0
        return
    rough, metal, f0, _reflection = props.fresnel_factor
    group.inputs["PBR Roughness"].default_value = rough
    group.inputs["PBR Metal"].default_value = metal
    group.inputs["PBR Specular"].default_value = min(max(f0 / F0_PER_LEVEL, 0.0), 1.0)
    if not group.inputs[MASK_SOCKET].is_linked:
        group.inputs[MASK_SOCKET].default_value = (1.0, 1.0, 1.0, 1.0)   # NullWhite: ORM = 1
    weight, radius = (0.0, (1.0, 1.0, 1.0))
    if props.func_lighting == THIN:
        weight, radius = principled_from_scatter(tuple(props.lightmap_factor[:3]))
    group.inputs["Subsurface DMC4"].default_value = weight
    group.inputs["Subsurface Radius DMC4"].default_value = radius


def _unlink(mat, socket_name, remove_images=True):
    """drop what feeds a group input; image nodes left with no use go too"""
    group = _group(mat)
    socket = _socket(group, socket_name)
    if socket is None:
        return
    nt = mat.node_tree
    for link in list(socket.links):
        node = link.from_node
        nt.links.remove(link)
        if remove_images and node.type == "TEX_IMAGE" and not any(out.links for out in node.outputs):
            nt.nodes.remove(node)


def make_pbr(mat, notes=None):
    """a classic DMC4 material as PBR: textures kept, roughness from its SpecularPow, metal 0, F0 0.04, reflections
    1; its mask (a specular colour) and the classic thin-surface term are dropped. Raises if the key has no PBR
    shader (nothing changed then)."""
    notes = notes if notes is not None else []
    props = props_of(mat)
    if props.func_specular == RIM:
        return notes
    lighting = props.func_lighting
    functions = functions_of(props, func_lighting=SH4SPOT if lighting == THIN else lighting)
    reason = unsupported_reason(functions)
    if reason is not None:
        raise AlbamCheckFailure(f"{mat.name} can't be a PBR material", details=reason,
                                solution="Change the material's functions in its DMC4 properties first")
    rough = roughness_from_power(props.fresnel_factor[2]) if props.func_specular != "0x0" else 1.0
    _unlink(mat, MASK_SOCKET)
    _unlink(mat, "Translucency", remove_images=False)
    if lighting != EMIT:
        _unlink(mat, "Emission DMC4", remove_images=False)   # the classic environment-cube term
    if lighting == THIN:   # classic THIN: additional R = translucent where 1; PBR reads it as thickness
        props.func_lighting = SH4SPOT
        props.lightmap_factor = DEFAULT_LIGHTMAP_FACTOR
        _unlink(mat, ADDITIONAL_SOCKET)
        notes.append(f"{mat.name}: its thin-surface lighting was turned off (PBR uses it for subsurface scattering)")
    props.func_specular = RIM
    props.envmap_bias = ENV_BIAS
    props.fresnel_factor = (rough, 0.0, DEFAULT_F0, DEFAULT_REFLECTION)
    update_display(mat)
    return notes


def make_classic(mat):
    """a PBR material back to the stock shading: no specular map (the ORM mask isn't a specular colour), SpecularPow
    from its roughness, no subsurface scattering"""
    props = props_of(mat)
    if props.func_specular != RIM:
        return
    rough = props.fresnel_factor[0]
    power = power_from_roughness(rough)
    _unlink(mat, MASK_SOCKET)
    if props.func_lighting == THIN:
        props.func_lighting = SH4SPOT
        props.lightmap_factor = DEFAULT_LIGHTMAP_FACTOR
        _unlink(mat, ADDITIONAL_SOCKET)
    props.func_specular = "0x0"
    props.envmap_bias = 0
    props.fresnel_factor = (0.0, 0.0, power, 0.0)
    update_display(mat)
    group = _group(mat)
    if group is not None:
        group.inputs[MASK_SOCKET].default_value = (0.0, 0.0, 0.0, 1.0)   # SPECULAR_NONE
        if _socket(group, "Roughness") is not None:
            group.inputs["Roughness"].default_value = 1.0


# ---- the material's PBR values as fields (get / set over the DMC4 custom properties) ----

def _getter(index):
    def get(self):
        return props_of(self.id_data).fresnel_factor[index]
    return get


def _setter(index, scale=1.0):
    def set_(self, value):
        props = props_of(self.id_data)
        values = list(props.fresnel_factor)
        values[index] = value * scale
        props.fresnel_factor = values
        update_display(self.id_data)
    return set_


def _get_specular(self):
    return props_of(self.id_data).fresnel_factor[2] / F0_PER_LEVEL


def _get_subsurface(self):
    return props_of(self.id_data).func_lighting == THIN


def _set_subsurface(self, on):
    mat = self.id_data
    props = props_of(mat)
    if on == (props.func_lighting == THIN):
        return
    props.func_lighting = THIN if on else SH4SPOT
    if on and tuple(props.lightmap_factor[:3]) == DEFAULT_LIGHTMAP_FACTOR[:3]:
        props.lightmap_factor = (0.5, 0.2, 0.12, props.lightmap_factor[3])   # skin
    update_display(mat)


def _get_scatter(self):
    return tuple(props_of(self.id_data).lightmap_factor[:3])


def _set_scatter(self, value):
    props = props_of(self.id_data)
    props.lightmap_factor = (value[0], value[1], value[2], props.lightmap_factor[3])
    update_display(self.id_data)


@blender_registry.register_blender_props_to_type("Material", "albam_pbr")
class AlbamPbrMaterial(bpy.types.PropertyGroup):
    """A DMC4 PBR material's values, stored in its DMC4 custom properties (fresnel_factor, func_lighting,
    lightmap_factor)"""
    roughness: bpy.props.FloatProperty(
        name="Roughness", min=0.0, max=1.0, get=_getter(0), set=_setter(0),
        description="How rough the surface is: 0 mirror-like, 1 fully matte. With an ORM mask texture this "
                    "scales its green channel (1 = the texture as painted)")
    metal: bpy.props.FloatProperty(
        name="Metal", min=0.0, max=1.0, get=_getter(1), set=_setter(1),
        description="1 for metal (coloured reflections, no diffuse colour), 0 for everything else. With an ORM mask "
                    "texture this scales its blue channel")
    specular: bpy.props.FloatProperty(
        name="Specular", min=0.0, max=1.0, get=_get_specular, set=_setter(2, F0_PER_LEVEL),
        description="How strongly a non-metal surface reflects when seen face-on, as Blender's Specular IOR Level: "
                    "0.5 (4 %) suits most materials, 0.35 skin. Metals take their reflection colour from the base "
                    "colour instead")
    reflection: bpy.props.FloatProperty(
        name="Reflection", min=0.0, soft_max=1.0, get=_getter(3), set=_setter(3),
        description="Strength of the reflected surroundings (the stage's ambient light): 1 is physically right, 0 "
                    "turns them off. Highlights from lights aren't affected")
    subsurface: bpy.props.BoolProperty(
        name="Subsurface Scattering", get=_get_subsurface, set=_set_subsurface,
        description="Light spreads under the surface past the shadow line and shines through thin parts, as in "
                    "skin. Uses the game's thin-surface lighting, so it can't be combined with emission")
    scatter: bpy.props.FloatVectorProperty(
        name="Scatter Colour", size=3, min=0.0, max=1.0, subtype="COLOR", get=_get_scatter, set=_set_scatter,
        description="Per colour channel, how far light spreads past the shadow line (0 none, 1 far) and the colour "
                    "of light coming through thin parts. Skin is about (0.5, 0.2, 0.12)")


def dmc4_material(mat):
    """True for a material with the MT Framework group and DMC4 properties"""
    if mat is None or _group(mat) is None:
        return False
    try:
        props_of(mat)
    except Exception:
        return False
    return True


@blender_registry.register_blender_type
class ALBAM_OT_PbrMake(bpy.types.Operator):
    """Turn this DMC4 material into a PBR material for dmc4_hook's PbrMaterials: roughness from its specular
    power, metal 0. Its specular map is dropped (a PBR mask holds occlusion, roughness and metal instead). Without
    dmc4_hook the game draws it with a bright rim light"""
    bl_idname = "albam.pbr_make"
    bl_label = "Make PBR"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        mat = getattr(context, "material", None)
        return dmc4_material(mat) and not is_pbr(mat)

    def execute(self, context):
        try:
            notes = make_pbr(context.material)
        except AlbamCheckFailure:
            bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")
            return {"CANCELLED"}
        self.report({"INFO"}, "; ".join(notes) or f"{context.material.name} is a PBR material")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_PbrMakeClassic(bpy.types.Operator):
    """Turn this PBR material back into the game's own shading (works without dmc4_hook): its specular power comes
    from the roughness, its ORM mask and subsurface scattering are dropped"""
    bl_idname = "albam.pbr_make_classic"
    bl_label = "Make Classic"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        mat = getattr(context, "material", None)
        return dmc4_material(mat) and is_pbr(mat)

    def execute(self, context):
        make_classic(context.material)
        return {"FINISHED"}


def _image_on(mat, socket_name):
    socket = _socket(_group(mat), socket_name)
    if socket is None or not socket.is_linked:
        return None
    node = socket.links[0].from_node
    return node.image if node.type == "TEX_IMAGE" else None


@blender_registry.register_blender_type
class ALBAM_PT_PbrMaterial(bpy.types.Panel):
    bl_label = "DMC4 PBR"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return dmc4_material(getattr(context, "material", None))

    def draw(self, context):
        mat = context.material
        layout = self.layout
        if not is_pbr(mat):
            layout.label(text="Classic material (the game's own shading)", icon="INFO")
            layout.operator("albam.pbr_make", icon="SHADING_RENDERED")
            return
        props = props_of(mat)
        reason = unsupported_reason(functions_of(props))
        if reason is not None:
            layout.label(text=f"No PBR shader: {reason}", icon="ERROR")
        col = layout.column()
        col.use_property_split = True
        values = mat.albam_pbr
        mask = _image_on(mat, MASK_SOCKET)
        col.prop(values, "roughness", text="Roughness" + (" x" if mask else ""))
        col.prop(values, "metal", text="Metal" + (" x" if mask else ""))
        col.prop(values, "specular")
        col.prop(values, "reflection")
        layout.label(text=f"Mask (ORM): {mask.name}" if mask else "No mask texture: the values above are used as they are",
                     icon="IMAGE_DATA" if mask else "INFO")
        if props.func_lighting == EMIT:
            layout.label(text="Emissive (EMITSH4SPOT): no subsurface scattering", icon="LIGHT")
        else:
            box = layout.box()
            box.prop(values, "subsurface")
            if values.subsurface:
                row = box.row()
                row.use_property_split = True
                row.prop(values, "scatter")
                extra = _image_on(mat, ADDITIONAL_SOCKET)
                box.label(text=f"Thickness / scatter map: {extra.name}" if extra else
                          "No thickness map: scatters everywhere, nothing shines through", icon="INFO")
        layout.operator("albam.pbr_make_classic", icon="LOOP_BACK")
        layout.label(text="Needs dmc4_hook's PbrMaterials in the game", icon="INFO")
