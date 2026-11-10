# Edge glow: an outline that glows, a see-through inside

A material for DMC4 models that lights up only along the model's outline, in a colour you pick, and leaves the
inside clear: the Ninja Gaiden after image look. Use it on a ghost, a spectral copy of a character, an aura shell or an
effect model.

It uses only the game's own material shader (`XfMaterialStandard`), so the model works in the game as it is: no hook
code needed. dmc4_hook's AfterImage mod builds the same look at runtime on copies of the player, and this guide uses
the same settings.

## How it works

Three of the game's material features do the work together:

- **Additive blending.** The material adds its colour to what is behind it, so black adds nothing. The base texture
  is black, so the model's lit surface doesn't show.
- **The environment reflection.** The shader adds an environment cube's colour to the surface (the shine of metal
  and leather in the game). Here the cube is one flat colour: the glow colour.
- **The fresnel weight.** The shader scales that reflection by a weight from the material's FresnelFactor, which
  depends on how much the surface faces the camera. The settings below make the weight 1 at the outline and 0 on
  surfaces that face the camera.

## Steps

1. **Start from a DMC4 material.** Use a model imported from the game, or make one with **New DMC4 Model** (see
   [new_model.md](new_model.md)). For a glowing copy of a character, import the character and give the copy its own
   game path, so the original stays as it is. Every material of the model needs the steps below. To set one material
   up and copy it to the rest, use the copy / paste buttons at the top of **Custom Properties (Albam)**, then plug in
   the same three images.
2. **Plug in three images** (Shader Editor). Connect an Image Texture node to each of these inputs of the material's
   **MT Framework** group node, replacing what was there:

   | Input | Image |
   |---|---|
   | Diffuse BM | plain black (any size; 8 x 8 is enough) |
   | Specular MM | plain white, or keep the model's own mask (see "Surface detail" below) |
   | Environment CM | the glow colour as a flat image, e.g. 8 x 8 of light blue |

   Ordinary PNG / TGA / JPG images are fine: export converts them. An image in Environment CM becomes a cube
   texture (`_CM`). A flat image goes on all six faces. A vertical strip of six square faces (+X -X +Y -Y +Z -Z from
   the top) keeps its faces, so the glow's colour can depend on which way the surface faces.
3. **Set the material** in **Material Properties > Custom Properties (Albam)**:

   | Setting | Value | Why |
   |---|---|---|
   | Attribute | `ATTR_TRANSPARENT` | blended, drawn after the solid models |
   | Blend State | `44171813` (= 0x02A20225) | additive. The default, 44172837, is ordinary alpha blending |
   | Alpha Reference | `0` | nothing is cut out |
   | Z-write | off | the model doesn't hide what is drawn after it |
   | Fog Enable | off | fog would tint the inside (see Limits) |
   | func specular map | `SPECULAR_STANDARD` | the reflection is part of the specular term |
   | FresnelFactor | `f`, `-f`, `200`, brightness | the edge weight (table below), small light highlights, the glow's brightness |
   | Transparency | 0 - 1 | overall strength: it scales the added colour |

   FresnelFactor's four values are FresnelFactor, FresnelBias, SpecularPow and EnvMapPower.
   - The first two set how far the glow reaches in from the outline: `f = 1 / ((1 + r)^5 - 1)`, with r between 0
     (the outline only) and 1 (everything but what faces the camera head-on).
   - SpecularPow 200 keeps the scene lights' highlights, which the same weight scales, down to points.
   - EnvMapPower is the brightness: 1 gives about the glow colour itself at the outline.

   | Reach r | FresnelFactor | FresnelBias | The glow covers surfaces turned more than |
   |---|---|---|---|
   | 0.1 | 1.638 | -1.638 | 84 deg from the camera (a thin line) |
   | 0.2 | 0.672 | -0.672 | 78 deg |
   | 0.35 | 0.287 | -0.287 | 70 deg (AfterImage's default) |
   | 0.5 | 0.152 | -0.152 | 60 deg |
   | 0.75 | 0.0649 | -0.0649 | 41 deg |
   | 1.0 | 0.0323 | -0.0323 | all but the parts facing the camera |

   The glow fades linearly from the outline to that angle.
4. **Export** the model as usual. Albam refuses a combination of material functions the game has no shader for and
   says which. Keep the model's normal map (`NORMALMAP_STANDARD`): the outline follows its bumps.

The viewport doesn't show the glow. Albam previews blending from the Attribute only, and draws the environment
reflection only for materials it imported. Check the result in the game.

## Surface detail

The mask (Specular MM) multiplies the glow. A white mask gives an even outline. The model's own mask, the game's
`_MM` texture, makes the glow follow the clothes' and skin's shine, so seams, buckles and folds show in the outline.

## Limits

- **Don't fade the model through the game's model transparency.** In the game, a material whose model is faded below
  full opacity at runtime (`cMaterial::beginDraw` 0xA61A70: `mAlpha` < 1) is drawn with ordinary alpha blending
  instead of its own blend. The additive glow then turns into a dark, see-through copy. Fade it through the
  material's blend factor instead: the file's Transparency, or `mDiffuseColor.w` (+0x3C) at runtime, which is what
  AfterImage does.
- **AfterImage's Copy models option** loads other models for the copies. With "Glowing edges" on, the mod still swaps
  in its own glow textures and settings, so those models need no glow material. With it off, the mod fades the copies
  through the model transparency, so a glow model would turn into the dark copy above.
- **A faint haze is possible.** The shader adds a constant (`gXfLDR2Offset`) to every pixel it draws, so a faint
  haze may show over the inside. Fog Enable off should keep the fog colour off it, but whether that flag reaches the
  shader's fog switch isn't checked.
- **Occlusion.** The vertex occlusion term (tangent w, `mtfw_tangent_w` in Albam) multiplies the glow, so creases an
  imported model darkens glow less.

## The formula

The pixel shader's specular end (`XfMaterialStandard.bfx`, details in `Vibed\RE\cMaterialStandard.md` "Blending, fade
and the specular rim at runtime"):

```
x      = 1 + cos(angle between the surface normal and the direction to the camera)    1 at the outline, 2 face-on
weight = 1 - saturate(FresnelFactor * x^5 + FresnelBias)
spec   = (envCube.rgb / envCube.a * EnvMapPower + lights' specular) * mask * weight * occlusion
colour = diffuse light * base + spec
```

With FresnelFactor `f` and FresnelBias `-f`, `weight = 1 - f (x^5 - 1)`, clamped to 0..1. It is 1 at the outline
(x = 1) and reaches 0 where `x = 1 + r`. The game's own materials use FresnelFactor 0 or very small values (0.004,
0.01, 0.05) because x^5 grows to 32 on surfaces facing the camera.
