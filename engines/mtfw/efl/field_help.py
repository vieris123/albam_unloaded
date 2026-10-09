"""Plain-language help for every .efl field, shown in the Effect Editor's field tooltips.

Keys are "<slot>:<field name>" with slot gen / ptcl / life / move / collision / culling. The texts say what a
field does in game and how to use it; the layout evidence stays in schema.py's notes. "Probably" marks an inferred
meaning.
"""

HELP = {
    # -- gen -------------------------------------------------------------------------------------------------
    'gen:AxisFlags': 'Packed word holding Order, AxisType and RelationType. Edit those fields instead.',
    'gen:AxisType': "Not understood yet (the name suggests an axis choice); keep the game's value.",
    'gen:BurstNum': (
        'Number of bursts before the generator stops spawning. 0 = repeat forever (until the game ends the effect).'
    ),
    'gen:ExtVibrationPath': (
        'Path of the .vib rumble file used by the rumble request, without extension. Empty = none. Never used by DX9 '
        'effects.'
    ),
    'gen:GroupFlag': (
        'Variant filter. The record is only built when this shares a bit with the group mask the game passes when it '
        'spawns the effect, so different bits make different variants of one effect file. 0xFFFFFFFF = always built.'
    ),
    'gen:LoopFrameDist': (
        'Probably a fractional-frame spread applied to the burst length (LoopNum). Not simulated in Blender; keep the'
        " game's value."
    ),
    'gen:LoopNum': (
        'Length of each burst in frames: SetNum particles are spawned on every frame of it. Usually 1 (a single '
        'puff); values below 1 act as 1.'
    ),
    'gen:MaterialFlag': (
        'Floor filter. The record is only built when this shares a bit with the ground-surface type under the '
        'character, so one effect can show different parts on different floors. 0xFFFFFFFF = always built.'
    ),
    'gen:member_0x134': "Not understood yet; keep the game's value.",
    'gen:member_0x138': "Not understood yet; keep the game's value.",
    'gen:member_0x13d': "Not understood yet; keep the game's value.",
    'gen:member_0x50': "Not understood yet; keep the game's value.",
    'gen:member_0x60': "Not understood yet; keep the game's value.",
    'gen:Order': "Euler rotation order used by the generator's rotation keyframe (Keys tab).",
    'gen:ParentNo': (
        'Game joint number the generator is attached to; -1 = not attached (it sits at the effect origin). Parent the'
        ' Empty to a bone to change it.'
    ),
    'gen:ParticleScale': (
        'Size multiplier for every particle this generator spawns (sprites, polygons, models, and rope or cloth '
        'lengths). 1 = unchanged.'
    ),
    'gen:Pos': (
        'Offset of the generator from its parent joint (or the effect origin when not attached), in cm, Y up. Move '
        "the record's Empty to change it."
    ),
    'gen:Quat': (
        "Rotation of the generator relative to its parent joint, as a quaternion (x, y, z, w). Rotate the record's "
        'Empty to change it.'
    ),
    'gen:RandomNo': (
        'Probably a table of random seeds, of which the game picks one (among the first RandomNoNum entries) when the'
        " effect starts. Not fully understood; keep the game's values."
    ),
    'gen:RandomNoNum': (
        'Probably how many entries of RandomNo are in use; the game picks one of them at random when the effect '
        "starts. Keep the game's value."
    ),
    'gen:Range': (
        'Size of the spawn area along X, Y, Z in cm, used by RangeType. Box: half-size per axis (only the base is '
        'used). Cylinder and sphere: radius, from the base out to base + rand, mostly near the base.'
    ),
    'gen:RangeDirType': (
        "Bends each particle's starting direction using its spawn position: 0 none, 1 Diffuse (away from the "
        'generator centre), 2 Converge (toward it), 3 Unit (not understood yet). The amount is UknRangeThing [0]; it '
        'has no effect with a point spawn shape.'
    ),
    'gen:RangeDivideNum': (
        '0 = random spawn positions. N > 0 = particles take N + 1 evenly spaced steps over the shape in spawn order '
        '(along the box axis, around the ring, top to bottom on a sphere), and on the strip.'
    ),
    'gen:RangeOptionFlags': "Not understood yet; keep the game's value.",
    'gen:RangeStripFlag': (
        'Strip spawn options (bits): 0x01 walk the strip in spawn order, 0x02 walk it in reverse (neither = random), '
        '0x08 strip is a closed loop, 0x10 use the segment midpoint instead of a random spot, 0x20 pick a random part'
        ' (ignores RangeStripPartsNo).'
    ),
    'gen:RangeStripPartsNo': (
        'Which part (curve) of the .efs strip to spawn on, counting from 0. Ignored when RangeStripFlag 0x20 (random '
        'part) is set.'
    ),
    'gen:RangeStripPath': (
        'Path of an .efs strip (curve) file, without extension. When set, particles spawn on this curve (scaled by '
        'UknRangeThing [1]-[3]), on top of the RangeType offset. Empty = no strip.'
    ),
    'gen:RangeStripType': (
        'How a spawn point is picked on the RangeStripPath strip: 0 = on one of its vertices, 1-3 = somewhere along a'
        ' segment between two vertices.'
    ),
    'gen:RangeType': (
        'Shape of the spawn area, sized by Range: 0 point (at the generator), 1-3 box (the axis X/Y/Z is the one '
        'RangeDivideNum steps along), 4-6 ring/cylinder around X/Y/Z, 7 sphere, 8 upper hemisphere (+Y).'
    ),
    'gen:RelationType': (
        "How the generator follows its joint (or the owner): 0 fully (position and rotation), 2 position only: it "
        'moves with the joint but keeps its own rotation in world axes. In Blender a type 2 generator on a bone gets a '
        "companion Empty named <record>_rot: rotate that one; its rotation is exported as Quat. 3 ignores the parent."
    ),
    'gen:Scale': (
        "Scale of the generator along X, Y, Z. It scales the generator's space (spawn area, path offsets); particle "
        "size only follows it when the particle's ParticleOptionFlag 0x200 is set. The base is the Empty's scale; a "
        'Scale keyframe replaces it.'
    ),
    'gen:SeOptionFlag': 'Bit 0x1 = stop the sound when the effect finishes. Never used by DX9 effects.',
    'gen:SeReqNo': 'Probably which sound of the .srq file to play. Never used by DX9 effects.',
    'gen:SetFrame': (
        'Pause in frames between the end of one burst and the start of the next. Together with LoopNum and BurstNum '
        'it sets the emission rhythm.'
    ),
    'gen:SetFrameDist': (
        'Probably a fractional-frame spread applied to the pause between bursts (SetFrame). Not simulated in Blender;'
        " keep the game's value."
    ),
    'gen:SetNum': 'Particles spawned on each spawning frame of a burst. 0 = none. A SetNum keyframe replaces it.',
    'gen:someJointIdx': (
        "Not understood yet (the name suggests a joint number, but that is unconfirmed); keep the game's value."
    ),
    'gen:SoundRequestPath': (
        'Path of a .srq sound request file, without extension. When set, a sound is requested when the generator '
        'starts. Empty = no sound. Never used by DX9 effects.'
    ),
    'gen:uknRangeFlag': "Not understood yet; keep the game's value.",
    'gen:UknRangeThing': (
        '[0] = how strongly RangeDirType bends the direction (0 = keep the Move direction, 1 = fully outward or '
        'inward). [1]-[3] = multipliers on the spawn position along X, Y, Z, for both the shape and the strip; 1 = '
        'unchanged.'
    ),
    'gen:VibOptionFlag': 'Bit 0x1 = stop the rumble when the effect finishes. Never used by DX9 effects.',
    'gen:VibPriority': 'Priority passed with the rumble request. Never used by DX9 effects.',
    'gen:VibReqArg0': (
        'Extra value passed with the rumble request; its meaning is not understood yet. Never used by DX9 effects.'
    ),
    'gen:VibReqArg1': (
        'Extra value passed with the rumble request; its meaning is not understood yet. Never used by DX9 effects.'
    ),
    'gen:VibReqNo': 'Which rumble entry of the .vib file to play. Never used by DX9 effects.',
    'gen:VibReqType': (
        "Controller rumble when the generator starts: 0 none, 1 plain, 2 at the generator's position (weaker with "
        'distance), 3 attached to the parent joint. Never used by DX9 effects.'
    ),
    'gen:WaitFrame': (
        'Delay in game frames (60 per second) before this generator starts spawning, counted from when the effect '
        'starts. Use it to stagger the parts of an effect. Any rumble or sound request also fires at that moment.'
    ),

    # -- ptcl ------------------------------------------------------------------------------------------------
    'ptcl:Angle': (
        'Rotation of the billboard on screen, in radians (3.14 = half a turn). Use the random part to give each '
        'particle a different angle.'
    ),
    'ptcl:AngleAdd': (
        'Spin of the billboard in radians per frame. Ignored when the angle has a keyframe (unless it is init-only).'
    ),
    'ptcl:AnimFlag': (
        'Flipbook playback: 1 play (advance by PatSpeed), 2 loop, 4 play backwards, 8 remove the particle when the '
        'flipbook ends (otherwise it holds the last frame). 0x100 flips the texture horizontally, 0x200 vertically, '
        '0x1000 rotates it. 0x400 / 0x800 flip each particle horizontally / vertically at random (half of them), '
        'which makes repeated particles look less alike.'
    ),
    'ptcl:AnimPath': (
        'The .ean flipbook table (game path without extension, e.g. effect\\ean\\com\\ec032_16) that lists where each '
        "frame sits on the texture sheet. It should match BaseMapPath's texture."
    ),
    'ptcl:AnimSpeed': (
        "How fast the particle steps through the model's mesh groups, in groups per frame, like a flipbook. Only used"
        ' when ModelAnimFlag bit 1 is set.'
    ),
    'ptcl:AspectRatio': (
        'Width multiplier of the billboard (height stays the same): 2 = twice as wide, 0.5 = half as wide. Limited to'
        ' 0-15.9.'
    ),
    'ptcl:AspectRatioAdd': (
        'Probably added to AspectRatio every frame, so the billboard stretches or narrows over time. Not verified.'
    ),
    'ptcl:AttenuateEnd': (
        "Distance in cm, times the particle scale, at which the light reaches zero: the light's reach. Keep it larger"
        ' than AttenuateStart.'
    ),
    'ptcl:AttenuateEndAdd': (
        "Change of AttenuateEnd per frame; negative values make the light's reach shrink over time."
    ),
    'ptcl:AttenuateStart': (
        'Distance in cm, times the particle scale, at which the light starts to fade. The brightness falls off '
        'linearly from here to AttenuateEnd.'
    ),
    'ptcl:AttenuateStartAdd': 'Change of AttenuateStart per frame, e.g. to grow or shrink a flash.',
    'ptcl:Axis': (
        'The axis the PrimModel is built around: 0 X, 1 Y (up), other values Z. A Ring around Y stands upright as a '
        'cylinder, or lies flat when its two heights are equal.'
    ),
    'ptcl:BaseMapPath': (
        'The colour texture, as a game path without extension (e.g. effect\\tex\\com\\ec032_16_BM). The .tex file must '
        'exist in the game files.'
    ),
    'ptcl:BlendDst': (
        'What happens to the background behind the particle. 5 (INVSRCALPHA) = normal blending, the particle covers '
        'the background by its alpha; 1 (ONE) = additive, the particle brightens it (fire, sparks, glows).'
    ),
    'ptcl:BlendOp': (
        'How the particle and background are combined. 0 (ADD) is normal; 2 (REVSUBTRACT) subtracts the particle from'
        ' the background, which darkens it (smoke, shadows).'
    ),
    'ptcl:BlendRate': (
        'Mixes the two pull directions along the rope: 0 = ChainRot everywhere, 0.5 = ChainRot at the root fading to '
        'BlendRot at the tip, 1 = BlendRot everywhere. Can be keyframed.'
    ),
    'ptcl:BlendRot': (
        'Angles in radians that turn the ChainBlendRotAxis direction into the second pull direction, mixed in toward '
        'the tip by BlendRate. Can be keyframed.'
    ),
    'ptcl:BlendSrc': (
        "How much of the particle's own colour is drawn. 4 (SRCALPHA) is the usual choice: colour times alpha. "
        'Together with BlendDst: 4 + 5 = normal see-through blending, 4 + 1 = additive glow.'
    ),
    'ptcl:ChainAcceleration': (
        'Strength of the pull on every rope point each frame (cm per frame, per frame) along the ChainRot/BlendRot '
        'direction. It acts like gravity for the rope.'
    ),
    'ptcl:ChainBlendRotAxis': (
        'Packed byte for the BlendRot pull: the low 4 bits pick the base axis (0 +X, 1 -X, 2 +Y, 3 -Y, 4 +Z, 5 -Z), '
        'the high 4 bits the rotation order (as RotOrder).'
    ),
    'ptcl:ChainBlendRotAxisType': (
        'Low 4 bits of ChainBlendRotAxis: the base axis BlendRot turns into the second pull direction (0 +X, 1 -X, 2 '
        '+Y, 3 -Y, 4 +Z, 5 -Z).'
    ),
    'ptcl:ChainBlendRotOrder': (
        'High 4 bits of ChainBlendRotAxis: the rotation order used to apply BlendRot (as RotOrder).'
    ),
    'ptcl:ChainForceRate': (
        'Strength of external wind on the rope when ChainOptionFlag 0x10 is set. The wind is zero unless the stage '
        'sets it.'
    ),
    'ptcl:ChainOptionFlag': (
        'Rope options (bits). 0x10: external wind can push the rope (ChainForceRate). 0x20: BlendRot is turned along '
        'with the ChainRot direction. 1 / 2: the ChainRot / BlendRot pulls stay fixed in the world instead of turning'
        ' with the generator.'
    ),
    'ptcl:ChainRot': (
        'Angles in radians that turn the ChainRotAxis direction into the main pull direction of the rope. Can be '
        'keyframed.'
    ),
    'ptcl:ChainRotAxis': (
        'Packed byte for the ChainRot pull: the low 4 bits pick the base axis (0 +X, 1 -X, 2 +Y, 3 -Y, 4 +Z, 5 -Z), '
        'the high 4 bits the rotation order (as RotOrder).'
    ),
    'ptcl:ChainRotAxisType': (
        "Low 4 bits of ChainRotAxis: the base axis ChainRot turns into the rope's main pull direction (0 +X, 1 -X, 2 "
        '+Y, 3 -Y, 4 +Z, 5 -Z).'
    ),
    'ptcl:ChainRotOrder': 'High 4 bits of ChainRotAxis: the rotation order used to apply ChainRot (as RotOrder).',
    'ptcl:ClothConstOffFrame': (
        'With ClothParam 1 or 2: frames after spawn before the cloth lets go of its head (1) or its tail (2); after '
        'that only the other end holds the rope.'
    ),
    'ptcl:ClothDistConvFrame': (
        'With ClothParam 4: how many frames the rope length takes to catch up with the distance between its two ends '
        '(plus ClothDistExpansion). 0 = at once.'
    ),
    'ptcl:ClothDistExpansion': (
        'With ClothParam 4: extra length in cm added to the distance between the two ends. Positive makes the rope '
        'sag, negative pulls it tight.'
    ),
    'ptcl:ClothParam': (
        'Option bits for CHAIN cloth. 1: let go of the head after ClothConstOffFrame frames (the rope then hangs from'
        ' the tail); 2: let go of the tail instead (it hangs from the particle); 4: the rope length follows the '
        'distance between its ends plus ClothDistExpansion, catching up over ClothDistConvFrame frames.'
    ),
    'ptcl:ClothSubRange': (
        "Where the cloth's tail point sits around the generator, in cm: a shape like the generator's Range "
        '(ClothSubRangeType picks it), with a point picked per particle. Scaled by ParticleScale.'
    ),
    'ptcl:ClothSubRangeDivideNum': (
        '0 = random tail points. N > 0 = particles take N + 1 evenly spaced steps over the tail shape in spawn order '
        '(like RangeDivideNum).'
    ),
    'ptcl:ClothSubRangeType': (
        'Shape of the tail-point area, with the same values as RangeType: 0 point, 1-3 box, 4-6 ring around X/Y/Z, 7 '
        'sphere, 8 upper hemisphere.'
    ),
    'ptcl:ClothType': (
        'Shape of a cloth line (cloth particle types, LineType 5): 0 CHAIN, a rope from the particle to a tail point '
        'that sags under a constant pull; 1 CURVE, a smooth bend between the two ends; 2 ZIGZAG, the bend plus random'
        ' jitter that looks like lightning. Each type has its own extra settings after the block, so switching only '
        'works if that data is there.'
    ),
    'ptcl:Color0': (
        'Tint colour and alpha of the particle; the texture is multiplied by it. Lower the alpha to make the particle'
        ' more transparent. A colour keyframe replaces it over time.'
    ),
    'ptcl:Color1': (
        'Probably the other end of a random colour range: each particle gets a colour between Color0 and Color1. Set '
        'it equal to Color0 for one fixed colour.'
    ),
    'ptcl:ColorFlag': (
        'How each particle picks its start colour between Color0 and Color1: the ticked channels (red, green, blue, '
        'alpha) are mixed toward Color1 by a random amount; with Each Channel Random every channel gets its own '
        'amount, otherwise they share one, so the colour stays on the line between the two. None ticked = Color0.'
    ),
    'ptcl:ColorPlaceInpType': (
        'Easing of the colour gradient (along the line, or across a PrimModel): 0 linear, 1 fast start (sine), '
        '2 slow start (1 - cos), 3 smooth at both ends.'
    ),
    'ptcl:ColorPlaceNo': (
        'Point index used by the colour gradient modes that blend toward a given point (ColorPlaceType 2 peak at, 3 '
        "from, 4 up to this point); point 0 is the head. On PolygonStrip it isn't read by the DX9 game."
    ),
    'ptcl:ColorPlaceType': (
        'Colour gradient across the mesh rows: 0 none, 1 linear, 2 peak at HoriColorPlaceNo, 3 from that row, 4 up to'
        ' that row.'
    ),
    'ptcl:CullingFlag': (
        'Culling switches. Distance / Angle Fade (0x1) turns on the fade set in the culling block (More tab): the '
        'particle fades with distance or view angle and is hidden when the fade reaches 0. Occlusion Test (0x2) hides '
        "it behind geometry (and turns refraction off). Per Particle (0x4) works the fade out for each particle "
        'instead of once for the generator; Angle Fade (0x80) fades by the viewing angle.'
    ),
    'ptcl:VolumeBlendRate': (
        'Volume look, 0 = off. Any other value draws the particle with the game\'s volume shader (or the depth-volume '
        'or parallax one when those options are ticked), with this value as its strength; the files use 1 to 100, '
        'and most particles have it. The Blender preview ignores it. Refraction and the occlusion test take priority.'
    ),
    'ptcl:CurveCoef': (
        'How far the middle of the curve is pushed toward the bend direction, in cm (or relative to the end distance '
        'with CurveOptionFlag 1). 0 = a straight line; negative bends the other way.'
    ),
    'ptcl:CurveDirAxisType': (
        "6 = the bend direction stays as CurveRot sets it; other values turn it to follow the particle's direction of"
        ' travel.'
    ),
    'ptcl:CurveDirFlags': (
        'Packed byte: the low 4 bits are CurveDirAxisType, the high 4 bits CurveType. Edit those fields instead.'
    ),
    'ptcl:CurveOptionFlag': (
        'Option bits. 1: CurveCoef is relative to the distance between the ends (1 = bend as far as the ends are '
        'apart). ZIGZAG only: 0x200 limits the jitter to the average segment length, 0x400 rolls the jitter once '
        'instead of every ZigzagVertexUpdateFrame frames, 0x100 is probably an ease-in of the jitter (not previewed).'
    ),
    'ptcl:CurveRot': (
        'Direction the curve bends toward: angles in radians that turn the CurveRotAxisType axis, applied in '
        'CurveRotOrder. Can be keyframed.'
    ),
    'ptcl:CurveRotAdd': 'Change of CurveRot per frame (radians); turns the bend over time.',
    'ptcl:CurveRotAxis': (
        'Packed byte: the low 4 bits are CurveRotAxisType, the high 4 bits CurveRotOrder. Edit those fields instead.'
    ),
    'ptcl:CurveRotAxisType': (
        'Low 4 bits of CurveRotAxis: the base axis of the bend direction before CurveRot (0 +X, 1 -X, 2 +Y, 3 -Y, 4 '
        '+Z, 5 -Z).'
    ),
    'ptcl:CurveRotOrder': 'High 4 bits of CurveRotAxis: the rotation order used to apply CurveRot (as RotOrder).',
    'ptcl:CurveType': (
        'Shape of the bend: 0 = a smooth arch made of two curves meeting at the pushed-out midpoint; other values = a'
        ' sine arch (half a wave from end to end).'
    ),
    'ptcl:DiffuseFactor': 'Not read by the DX9 game (a Special Edition field); editing it has no effect.',
    'ptcl:DirAxisType': (
        '6 = the particle is not turned toward its direction of travel and keeps only its Rot (turning with the '
        'generator). Other values turn that axis (0 +X, 1 -X, 2 +Y, 3 -Y, 4 +Z, 5 -Z) along the direction of travel, '
        'e.g. for streaks (verified for Model, PrimModel and Polygon; the preview does it for those).'
    ),
    'ptcl:DistortRate': (
        "Stretches each corner's distance from the pivot, in the order top-left, top-right, bottom-left, bottom-right"
        ' of the quad. 1 = normal; different values give trapezoids and other skewed shapes.'
    ),
    'ptcl:DrawFlags_0x41': (
        '0x1 makes the PatNo keyframe set the flipbook speed (frames per frame) instead of the flipbook frame number.'
    ),
    'ptcl:EntryType': (
        'Probably picks the draw list (render layer) the particle is queued in. Not confirmed in the DX9 game; keep '
        "the game's value."
    ),
    'ptcl:FixFlags': (
        "Packed word of the FIX shape options; bits 4-7 are FixRotOrder. The other bits aren't understood yet; keep "
        'them.'
    ),
    'ptcl:FixModelScale': 'Scale of the stored FIX points along X, Y, Z. 1 = as stored.',
    'ptcl:FixModelScaleAdd': 'Change of FixModelScale per frame; positive grows the shape, negative shrinks it.',
    'ptcl:FixOtDepth': (
        'Fixed draw-order key (0 to 32767) used instead of the depth from the camera when ParticleOptionFlag has '
        'Fixed Sort Depth.'
    ),
    'ptcl:OtDepthBias': (
        'Moves the draw-order position this far toward the camera (cm) when ParticleOptionFlag has Sort Bias Toward '
        "Camera. 0 in every game file."
    ),
    'ptcl:FixPoint0': (
        "One of the line's stored points (LineType FIX), in cm in the particle's space, before FixModelScale and "
        'FixRot. There is one FixPoint per LineOfsNum.'
    ),
    'ptcl:FixPoint1': (
        "One of the line's stored points (LineType FIX), in cm in the particle's space, before FixModelScale and "
        'FixRot. There is one FixPoint per LineOfsNum.'
    ),
    'ptcl:FixRot': 'Rotation of the stored FIX shape, angles in radians per axis, applied in FixRotOrder.',
    'ptcl:FixRotAdd': 'Change of FixRot per frame (radians); spins the stored shape.',
    'ptcl:FixRotOrder': 'Bits 4-7 of FixFlags: the rotation order used to apply FixRot (as RotOrder).',
    'ptcl:FollowFrame': 'Not read by the DX9 game (a Special Edition field); editing it has no effect.',
    'ptcl:ForceVertexAttenuateRate': (
        'Probably how the wind strength changes from point to point along the rope (with ChainOptionFlag 0x10). Keep '
        "the game's value."
    ),
    'ptcl:FrameInf': (
        "Fraction of each rope point's velocity kept every frame. 1 = no damping (keeps swinging), lower values calm "
        'the rope down faster.'
    ),
    'ptcl:HeadSize': (
        'Half-width of the Polyline ribbon at its head, in cm, multiplied by the particle scale. If it drops to 0 or '
        'below while SizePlaceType is 0, the particle disappears.'
    ),
    'ptcl:HeadSizeAdd': (
        'Change of HeadSize per frame (negative values make the ribbon thinner over time). Ignored while a HeadSize '
        'keyframe is set.'
    ),
    'ptcl:Height': (
        'Polygon: half the height of the quad in cm (the quad is twice this tall), multiplied by Scale. PrimModel: '
        'two values; Ring = the heights of its two edge rings (equal heights give a flat disc or ring), Sphere = '
        'vertical radius and vertical offset, Grid = the depths of its two edges.'
    ),
    'ptcl:HeightAdd': (
        'Polygon: added to Height every frame; if the height shrinks to 0 or less the particle is removed. PrimModel:'
        ' added to the two Height values every frame. Ignored when the value has a keyframe (unless it is init-only).'
    ),
    'ptcl:HoriColorPlaceNo': 'The row used as the turning point of the ColorPlaceType gradient.',
    'ptcl:HoriDivNum': (
        'Number of rows along the axis: bands between the two rings (Ring), latitude bands (Sphere) or rows (Grid).'
    ),
    'ptcl:HoriDrawEnd': 'Last row that is drawn (inclusive). HoriDivNum - 1 draws to the end.',
    'ptcl:HoriDrawStart': (
        'First row that is drawn (counted from 0). For a Sphere, drawing only the top rows makes a dome.'
    ),
    'ptcl:HoriTexDivNum': (
        'Textured types: 0 puts the whole texture on every row; N spreads one copy of the texture across N + 1 rows.'
    ),
    'ptcl:Intensity': (
        'Brightness multiplier on the colour (not the alpha), limited to 0-127. Values above 1 make additive effects '
        'glow brighter; a keyframe replaces it over time.'
    ),
    'ptcl:LayerDivideNum': 'Not read by the DX9 game (a Special Edition field); editing it has no effect.',
    'ptcl:Length': 'Total rope length in cm, split evenly between its points. Can be keyframed.',
    'ptcl:LengthAdd': (
        "Change of the rope's total length per frame (cm); positive grows it, negative shrinks it. Ignored while "
        'Length is keyframed.'
    ),
    'ptcl:LensFlarePath': (
        'The lens-flare resource this particle uses, as a game path without the extension. Lens flares are not '
        'previewed in Blender.'
    ),
    'ptcl:LightAttribute': (
        "How the Light particle's light is computed: SH (0x2, spherical harmonics), Per-Pixel (0x8; the game drops it "
        "when the light can't do per-pixel) or Simple (0x10). Every game file uses Simple. The Blender preview always "
        'uses a point light.'
    ),
    'ptcl:LightColorW': (
        "Passed to the light as the fourth component of its colour; the game's files use 1 or 2. Probably a "
        'brightness multiplier.'
    ),
    'ptcl:LightGroupFlag': (
        "Light-group mask, the same kind the game's models use (one bit per group). On a Light particle it is the "
        'groups its light shines on (0xFFFFFFFF = all, as most files do); a model is most likely lit when its own '
        'light group shares a bit with it. On other particles it makes them lit by lights of those groups; 0 = unlit (most '
        'effects; mainly Model particles use it). The Blender preview draws particles unlit.'
    ),
    'ptcl:LightMaskY': 'Not read by the DX9 game (a Special Edition field); editing it has no effect.',
    'ptcl:LightType': (
        "0 point light, 1 spot light. The game's effect files only use point lights, and the Blender preview always "
        'shows a point light.'
    ),
    'ptcl:LightTypeFlags': 'Packed byte holding LightType. Edit LightType instead.',
    'ptcl:LineFlags': (
        'Packed settings word for line particles: LineType, LineOfsNum and the colour gradient (ColorPlaceType, '
        'ColorPlaceInpType, ColorPlaceNo). Edit the individual fields instead.'
    ),
    'ptcl:LineLength': 'Length of the stick in cm; its LineOfsNum points are spread along it. Can be keyframed.',
    'ptcl:LineLengthAdd': "Change of the stick's length per frame (cm); positive grows it, negative shrinks it.",
    'ptcl:LineOfsNum': (
        'Number of points in each line, or in a PolygonStrip trail. For FOLLOW trails and sword trails one point is '
        'added per frame, so this is the trail length in frames; more points give a longer, smoother line. For FIX '
        'lines it is the number of stored points.'
    ),
    'ptcl:LineRot': (
        'Direction of the stick (LineType LENGTH): angles in radians that turn the LineRotAxisType axis, applied in '
        'LineRotOrder. Can be keyframed.'
    ),
    'ptcl:LineRotAdd': 'Change of LineRot per frame (radians); swings the stick.',
    'ptcl:LineRotAxisType': (
        'Bits 0-3 of LineRotFlags: the base axis of the stick before LineRot (0 +X, 1 -X, 2 +Y, 3 -Y, 4 +Z, 5 -Z).'
    ),
    'ptcl:LineRotFlags': (
        'Packed word: bits 0-3 are LineRotAxisType and bits 4-7 LineRotOrder. Edit those fields instead.'
    ),
    'ptcl:LineRotOrder': 'Bits 4-7 of LineRotFlags: the rotation order used to apply LineRot (as RotOrder).',
    'ptcl:LineType': (
        "How the line's points are placed. 0 FOLLOW: a trail of the particle's last positions; 1 FIX: a fixed shape "
        'stored in the file; 2 FIX_END: the trail pulled back toward the spawn point; 3 CHAIN: a hanging rope; 4 '
        'LENGTH: a rigid stick; 5 CLOTH: used by the cloth types. FIX, CHAIN and LENGTH need their own extra settings'
        ' after the block, so switching a record to one of them only works if that data is there.'
    ),
    'ptcl:MaskMapPath': (
        'Probably a mask texture (game path without extension). Almost never used; leave it empty unless the original'
        ' effect sets it.'
    ),
    'ptcl:member_0x1ac': "Not understood yet; keep the game's value.",
    'ptcl:member_0x38': "Not understood yet; keep the game's value.",
    'ptcl:member_0x3c': "Not understood yet; keep the game's value.",
    'ptcl:member_0x54': "Not understood yet; it is always 0 in the game's files, so keep it at 0.",
    'ptcl:member_chain_0x02': "Not used by the game's rope code; keep the game's value.",
    'ptcl:member_fix_0x64': "Not understood yet; keep the game's values.",
    'ptcl:member_line_0x34': "Not understood yet; keep the game's value.",
    'ptcl:member_zigzag_0x7c': "Not understood yet (0 in every DX9 file); keep the game's value.",
    'ptcl:ModelAnimFlag': (
        'Option bits for Model particles. 1: step through mesh groups at AnimSpeed; 2: loop at the end; 4: step '
        'backwards; 8: kill the particle at the end; 0x10: scroll the texture by ScrollU/ScrollV (in DX9; the Special '
        'Edition renamed this bit to a random reverse); 0x10000: apply ModelZofs.'
    ),
    'ptcl:ModelBillboardType': (
        "Camera facing of the mesh: 0 = no camera facing; 1 = takes the camera's rotation, so it"
        ' lies flat in the screen plane (its own Rot still applies on top); 2, 3, 4 = keep the world X, Y or Z axis fixed and turn around it toward the camera (a cylindrical billboard, e.g. 3 for upright flames).'
        ' A tilted generator (e.g. on a bone) tilts it too, as in the game.'
    ),
    'ptcl:ModelFlags': (
        "Packed settings word for Model particles: RotOrder, DirAxisType (6 = don't turn with the movement "
        'direction), ModelBillboardType (1 = face the camera), PartsNoMin and PartsNoRange. Edit the individual '
        'fields instead.'
    ),
    'ptcl:ModelPath': (
        'The .mod drawn by each particle, as a game path without the extension. Only one mesh group of it is drawn '
        "(see PartsNoMin); the model's animations are not played."
    ),
    'ptcl:ModelScale': (
        'Scale of the mesh along X, Y and Z, on top of Scale. A scale keyframe replaces it over time.'
    ),
    'ptcl:ModelScaleAdd': (
        'Added to ModelScale every frame (per axis), so the mesh grows or shrinks; it stops at 0. Ignored when there '
        'is a scale keyframe (unless it is init-only).'
    ),
    'ptcl:ModelZofs': (
        'Moves the model along the line from the camera to the particle, in cm; negative values pull it toward the '
        'camera. Needs ModelAnimFlag 0x10000.'
    ),
    'ptcl:NormalMapPath': (
        'Probably a normal map texture (game path without extension). Almost never used; leave it empty unless the '
        'original effect sets it.'
    ),
    'ptcl:NormAttenuateAngleEnd': (
        'Where the rim fade (NormAttenuateFlag) ends, as an angle between the surface and the view. Units and '
        "direction aren't confirmed; adjust it relative to the game's values."
    ),
    'ptcl:NormAttenuateAngleStart': (
        'Where the rim fade (NormAttenuateFlag) starts, as an angle between the surface and the view. Units and '
        "direction aren't confirmed; adjust it relative to the game's values."
    ),
    'ptcl:NormAttenuateCurve': (
        "Probably the easing curve of the rim fade between its start and end angle. Keep the game's value."
    ),
    'ptcl:NormAttenuateFlag': (
        "Rim fade: any non-zero value fades the mesh's alpha by the angle between its surface and the view, over the "
        'NormAttenuateAngle range. Including the value 2 bit makes it one-sided.'
    ),
    'ptcl:ParticleOptionFlag': (
        'Drawing options. Draw order: Sort Each Particle sorts every particle by its own depth (otherwise the whole '
        'generator sorts as one), Fixed Sort Depth uses FixOtDepth, Sort at Owner sorts at the character or object '
        'that owns the effect, Keep Behind Camera still draws particles whose sort depth is behind the camera, Sort '
        'Bias Toward Camera moves the sort position by OtDepthBias. Look: Soft Edges fades where it meets geometry, '
        'Refraction bends the scene behind it, Full Resolution skips the reduced-size effect buffer, No Depth Test '
        'draws on top of everything, No Fog, Face Culling hides back faces, Parallax / Depth Volume pick the volume '
        'shader variant (with VolumeBlendRate). Size and rotation: World Scale follows the parent\'s scale, Scale '
        'After Rotation applies ModelScale along the turned axes, Ignore Generator Rotation keeps the particle on world '
        "axes (it doesn't turn with the generator or toward its movement), Keep Spawn Rotation adds the generator's "
        'rotation at spawn time and then keeps it (Model / PrimModel). Pivot at PatCenter, Extended '
        'Line Position (lines), Fade Edges (PrimModel border vertices fade to transparent).'
    ),
    'ptcl:PartsNoMax': (
        'Highest mesh group a keyframe on the part number can select; keyed values are clamped to it.'
    ),
    'ptcl:PartsNoMin': (
        'Which mesh group of the model is drawn: the first mesh whose group number equals this value. With '
        'PartsNoRange, each particle picks a group from PartsNoMin to PartsNoMin + PartsNoRange at random.'
    ),
    'ptcl:PartsNoRange': (
        'How many extra mesh groups above PartsNoMin a particle may pick at random. 0 always draws PartsNoMin.'
    ),
    'ptcl:PassBits': (
        'Extra view bits next to TransMode: the generator is drawn in a view if the view shares a bit with '
        'TransMode or with these (1 and 2 = view mode bits 8 and 9, which views clear by default). Which views set '
        "them isn't known yet; the files use 1 (most), 0 and 2. Keep the game's value."
    ),
    'ptcl:PatCenter': (
        'A pixel position inside the flipbook frame, from its top-left corner, used as the pivot: for billboards with'
        ' ParticleOptionFlag 0x10000, for polygons with PolygonFixType 9.'
    ),
    'ptcl:PatNoMax': (
        'Probably the highest flipbook frame the particle may use; the starting frame is clamped to it. Keep the '
        "game's value."
    ),
    'ptcl:PatNoMin': (
        'The flipbook frame (pattern) the particle starts on. With PatNoRange each particle starts on a random frame '
        'from PatNoMin to PatNoMin + PatNoRange.'
    ),
    'ptcl:PatNoRange': (
        "Random extra added to PatNoMin per particle (0 to this value, inclusive), so particles don't all show the "
        'same frame. 0 = all start on PatNoMin.'
    ),
    'ptcl:PatSpeed': (
        'Flipbook frames advanced per game frame (60 per second) when AnimFlag has the play bit: 1 = a new frame '
        'every frame, 0.5 = every 2 frames.'
    ),
    'ptcl:PlaceColor': (
        'Second colour for the gradient along a line or sword trail: the head uses the particle colour and the '
        'gradient blends toward this one (see ColorPlaceType). Each particle picks a random colour between the two '
        'entries. On PolygonStrip it is the tail colour when ColorPlaceType is not 0.'
    ),
    'ptcl:PlaceColor1': (
        'Probably the first colour of the ColorPlaceType gradient across the mesh rows. Has no effect when '
        'ColorPlaceType is 0.'
    ),
    'ptcl:PlaceColor2': (
        'Probably the second colour of the ColorPlaceType gradient across the mesh rows. Has no effect when '
        'ColorPlaceType is 0.'
    ),
    'ptcl:PlaceSize': (
        'Half-width of the Polyline ribbon at the other end of the width gradient, in cm, multiplied by the particle '
        'scale. Only used when SizePlaceType is not 0.'
    ),
    'ptcl:PlaceSizeAdd': 'Change of PlaceSize per frame. Ignored while a PlaceSize keyframe is set.',
    'ptcl:PolygonAxis': (
        'The plane the quad lies in: 0/1 the YZ plane (facing +X / -X), 2/3 the XZ plane (lying flat, good for ground'
        ' marks), 4/6 the XY plane facing +Z, 5 facing -Z.'
    ),
    'ptcl:PolygonBillBoardType': (
        "Camera facing of the quad: 0 = no camera facing; 1 = takes the camera's rotation, so it"
        ' lies flat in the screen plane (its own Rot still applies on top); 2, 3, 4 = keep the world X, Y or Z axis fixed and turn around it toward the camera (a cylindrical billboard, e.g. 3 for upright flames).'
        ' A tilted generator (e.g. on a bone) tilts it too, as in the game.'
    ),
    'ptcl:PolygonDivideNum': (
        'Splits the quad into this many + 1 strips when drawn. The shape looks the same; the preview ignores it.'
    ),
    'ptcl:PolygonFixType': (
        'The pivot the quad is placed and rotated around: 0 centre, 1-8 a corner or edge middle, 9 the PatCenter '
        'pixel. Width/Height growth extends away from the pivot, so e.g. a bottom pivot makes a quad grow upward.'
    ),
    'ptcl:PolygonFlags': (
        'Holds the polygon settings. Edit them through PolygonAxis, RotOrder, DirAxisType, PolygonFixType, '
        'PolygonBillBoardType and PolygonDivideNum.'
    ),
    'ptcl:PreUpdateLoopNum': (
        'Rope simulation steps run when it spawns, so it starts already settled (e.g. hanging) instead of straight. '
        'Raise it if the rope visibly swings into place on its first frames.'
    ),
    'ptcl:PrimFlags': (
        'Holds the PrimModel settings. Edit them through PrimModelType, Axis, RotOrder, DirAxisType, ColorPlaceType, '
        "ModelBillboardType and NormAttenuateFlag. Bits 20-23 aren't understood; keep them."
    ),
    'ptcl:PrimFlags2': "Not read by the DX9 game as far as known; keep the game's value.",
    'ptcl:PrimMaterialFlags': (
        'Holds the blend settings. Edit them through BlendSrc, BlendDst, BlendOp and PassBits.'
    ),
    'ptcl:PrimModelType': (
        'The generated mesh: 0 Ring (cylinder, cone, disc or ring), 2 Sphere (or dome), 4 Grid (flat sheet or '
        'trapezoid). The odd values (1 TexRing, 3 TexSphere, 5 TexGrid) are the textured versions; only those use the'
        ' texture and flipbook.'
    ),
    'ptcl:Radius': (
        'PrimModel size in cm, two values. Ring = the radii of its two edge rings (equal = cylinder, one 0 = cone or '
        'disc), Sphere = horizontal radius (second value unused), Grid = the widths of its two edges.'
    ),
    'ptcl:RadiusAdd': (
        'Added to the two Radius values every frame, e.g. for an expanding shockwave ring. Ignored when the value has'
        ' a keyframe (unless it is init-only).'
    ),
    'ptcl:Rot': (
        'Starting rotation of the particle around X, Y and Z, in radians, applied in RotOrder. Use the random parts '
        'for varied orientations.'
    ),
    'ptcl:RotAdd': (
        'Spin around X, Y and Z in radians per frame. Ignored when there is a rotation keyframe (unless it is init-'
        'only).'
    ),
    'ptcl:RotAddCoef': 'Not read by the DX9 game (a Special Edition field); editing it has no effect.',
    'ptcl:RotAxisOrder': (
        "Packed byte for PolygonStrip: RotAxisType (the axis the trail's width runs along) and RotOrder. Edit the "
        'individual fields instead.'
    ),
    'ptcl:RotAxisType': (
        "The local axis the sword trail's width runs along, before Rot is applied. Pick the axis that matches the "
        "blade's direction on the bone the effect is attached to."
    ),
    'ptcl:RotDivNum': (
        'Number of segments around the shape (Ring, Sphere) or columns (Grid). More segments are smoother but cost '
        'more.'
    ),
    'ptcl:RotDrawEnd': 'Last segment around the shape that is drawn (inclusive). RotDivNum - 1 draws to the end.',
    'ptcl:RotDrawStart': (
        'First segment around the shape that is drawn (counted from 0). With RotDrawEnd, draw only part of it for '
        'arcs and slices.'
    ),
    'ptcl:RotOrder': (
        "Order in which the X, Y and Z rotations of Rot are applied (first letter first, as in Blender's rotation "
        'mode): 0 XYZ, 1 XZY, 2 YXZ, 3 YZX, 4 ZXY, 5 ZYX. The game names these 0 ZYX ... 5 XYZ, which is not the '
        'order they apply. Only matters when more than one angle is non-zero.'
    ),
    'ptcl:RotTexDivNum': (
        'Textured types: 0 puts the whole texture on every segment around; N spreads one copy of the texture across N'
        ' + 1 segments.'
    ),
    'ptcl:Scale': (
        'Size of each particle. Billboards are this many cm per texture pixel; Polygon and PrimModel sizes are '
        'multiplied by it. A scale of 0 or less removes the particle.'
    ),
    'ptcl:ScaleAdd': (
        'Added to Scale every frame, so particles grow (positive) or shrink (negative). A particle that shrinks to 0 '
        'disappears. Ignored when Scale has a keyframe (unless it is init-only).'
    ),
    'ptcl:ScrollU': (
        'Texture scroll speed across U, in UV units per frame. Needs ModelAnimFlag 0x10. The offset wraps around, so '
        'small values (e.g. 0.01) give a steady flow.'
    ),
    'ptcl:ScrollV': 'Texture scroll speed across V, in UV units per frame. Needs ModelAnimFlag 0x10.',
    'ptcl:SeqNoMin': (
        'Which flipbook sequence of the .ean (AnimPath) the particle uses. With SeqNoRange each particle picks a '
        'random sequence from SeqNoMin to SeqNoMin + SeqNoRange.'
    ),
    'ptcl:SeqNoRange': (
        'Random extra added to SeqNoMin per particle (0 to this value, inclusive), for variety between particles. 0 ='
        ' all particles use SeqNoMin.'
    ),
    'ptcl:ShrinkCoef': "Not read by the DX9 game; keep the game's value.",
    'ptcl:SizePlaceFlags': (
        'Packed settings word for Polyline width and cloth: SizePlaceType, SizePlaceInpType, SizePlaceNo, ClothType '
        'and ClothParam. Edit the individual fields instead.'
    ),
    'ptcl:SizePlaceInpType': (
        'Easing of the width gradient along the ribbon: 0 linear, 1 fast start (sine), 2 slow start (1 - cos), 3 '
        'smooth at both ends.'
    ),
    'ptcl:SizePlaceNo': (
        'Point index used by SizePlaceType 2-4 (the point where the width reaches PlaceSize); point 0 is the head.'
    ),
    'ptcl:SizePlaceType': (
        'How the ribbon width changes from HeadSize (at the head, point 0) to PlaceSize: 0 HeadSize everywhere, 1 '
        'linear from head to tail, 2 PlaceSize at point SizePlaceNo and HeadSize at both ends, 3 HeadSize up to '
        'SizePlaceNo then toward PlaceSize at the tail, 4 toward PlaceSize up to SizePlaceNo then PlaceSize to the '
        'tail.'
    ),
    'ptcl:SplineDivideNum': (
        'Smoothing of the sword trail: each segment between two trail samples is split into this many quads along a '
        'smooth curve. Higher values give rounder arcs for fast swings.'
    ),
    'ptcl:SpotFlags': (
        "Spot-light settings, only used when LightType is 1. No effect in the game's files uses it, so its bits are "
        "not understood yet; keep the game's value."
    ),
    'ptcl:StretchScale': "Not read by the DX9 game; keep the game's value.",
    'ptcl:StripColorFlags': (
        'Packed byte for PolygonStrip: ColorPlaceType (not 0 = the tail fades to PlaceColor) and LayerDivideNum. Edit'
        ' the individual fields instead.'
    ),
    'ptcl:TextureInvH': (
        'Probably 1 / the texture height in pixels, used to turn the .ean pixel rectangles into texture coordinates. '
        "Keep the game's value unless you change the texture's size."
    ),
    'ptcl:TextureInvW': (
        'Probably 1 / the texture width in pixels, used to turn the .ean pixel rectangles into texture coordinates. '
        "Keep the game's value unless you change the texture's size."
    ),
    'ptcl:TexturePath': (
        'The texture drawn by MassBillboard particles, as a game path without the extension. This particle type is '
        'not previewed in Blender.'
    ),
    'ptcl:TransMode': (
        'Which render passes draw the particle (cTrans::MODE bits): 0x1 the normal view, 0x2 reflections, 0x4 '
        'receives shadows, 0x8 casts shadows, 0x10 environment map, 0x20 motion blur. Without 0x1 the particle '
        "isn't drawn normally, so use 1 (or 3) for a visible effect. The game's files use only 1, 0 and once 3. "
        "It is the same pass mask the game's models have. This is not a blend mode."
    ),
    'ptcl:VertexInf': (
        "Springiness: how much of each stretch correction is fed back into the rope's velocity. Higher values make "
        'the rope snap back and wobble more.'
    ),
    'ptcl:Width': 'Polygon: half the width of the quad in cm (the quad is twice this wide), multiplied by Scale.',
    'ptcl:WidthAdd': (
        'Added to Width every frame. If the width shrinks to 0 or less the particle is removed. Ignored when Width '
        'has a keyframe (unless it is init-only).'
    ),
    'ptcl:WidthPlaceRate': (
        "Where the particle sits across the trail's width: 0.5 centres the trail on it, 0 or 1 puts it on one edge so"
        ' the trail extends to one side only.'
    ),
    'ptcl:ZigzagEase': (
        "Probably the strength of the jitter's ease curve; (1, 1) in every DX9 file. Keep the game's value."
    ),
    'ptcl:ZigzagVertexAmplitude': (
        'Size of the random jitter along X, Y, Z in cm, in a frame whose Z runs from head to tail: each point moves '
        'by up to half this. Bigger = wilder lightning.'
    ),
    'ptcl:ZigzagVertexUpdateFrame': (
        'Frames between new random jitters, i.e. how fast the lightning flickers. Smaller = faster.'
    ),
    'ptcl:zOfs': (
        'Probably a depth offset used when sorting the particle against other transparent things. Not confirmed in '
        "the DX9 game; keep the game's value."
    ),

    # -- life ------------------------------------------------------------------------------------------------
    'life:AppearFrame': (
        "Fade-in time in frames: the particle's alpha ramps from 0 to full over this many frames after it spawns. 0 ="
        ' appears at full opacity.'
    ),
    'life:KeepFlags': (
        'Packed word holding KeepHoldFlag, KeyframeKeepFrameParamOffset and KeepHoldFrame. This split is an old guess'
        " that hasn't been checked against the game; edit the bit-fields or keep the game's value."
    ),
    'life:KeepFrame': (
        'Frames the particle stays fully visible after fading in. Total lifetime is Appear + Keep + Vanish frames.'
    ),
    'life:KeepHoldFlag': (
        'Probably keeps the particle in its Keep (fully visible) phase until something releases it, such as reaching '
        "the end of a path with PathOptionFlag 4, instead of counting KeepFrame down. Unverified; keep the game's "
        'value.'
    ),
    'life:KeepHoldFrame': (
        "Not understood yet; probably a frame count used with KeepHoldFlag. Keep the game's value."
    ),
    'life:KeyframeKeepFrameParamOffset': (
        'Probably an offset to a keyframe curve for KeepFrame. Life blocks in the game files never carry keyframe '
        'data, so leave it 0.'
    ),
    'life:VanishFrame': (
        'Fade-out time in frames: after the Keep phase the alpha ramps down to 0 over this many frames, then the '
        'particle dies. 0 = disappears instantly.'
    ),

    # -- move ------------------------------------------------------------------------------------------------
    'move:Acceleration': (
        'Added to the speed every frame along the launch direction (Add), or to the travel speed along the path (path'
        ' moves, and after release). Negative values slow the particle down and can reverse it.'
    ),
    'move:BlendRate': (
        'Mixes the two pull directions along the rope: 0 = ChainRot everywhere, 0.5 = ChainRot at the root fading to '
        'BlendRot at the tip, 1 = BlendRot everywhere. Can be keyframed.'
    ),
    'move:BlendRot': (
        'Angles in radians that turn the ChainBlendRotAxis direction into the second pull direction, mixed in toward '
        'the tip by BlendRate. Can be keyframed.'
    ),
    'move:ChainAcceleration': (
        'Strength of the pull on every rope point each frame (cm per frame, per frame) along the ChainRot/BlendRot '
        'direction. It acts like gravity for the rope.'
    ),
    'move:ChainBlendRotAxis': (
        'Packed byte for the BlendRot pull: the low 4 bits pick the base axis (0 +X, 1 -X, 2 +Y, 3 -Y, 4 +Z, 5 -Z), '
        'the high 4 bits the rotation order (as RotOrder).'
    ),
    'move:ChainForceRate': (
        'Strength of external wind on the rope when ChainOptionFlag 0x10 is set. The wind is zero unless the stage '
        'sets it.'
    ),
    'move:ChainOptionFlag': (
        'Rope options (bits). 0x10: external wind can push the rope (ChainForceRate). 0x20: BlendRot is turned along '
        'with the ChainRot direction. 1 / 2: the ChainRot / BlendRot pulls stay fixed in the world instead of turning'
        ' with the generator.'
    ),
    'move:ChainPosNum': (
        "Number of points (nodes) in the generator's rope that PathChain particles ride. More points give a smoother,"
        ' more flexible rope; at least 2.'
    ),
    'move:ChainRot': (
        'Angles in radians that turn the ChainRotAxis direction into the main pull direction of the rope. Can be '
        'keyframed.'
    ),
    'move:ChainRotAxis': (
        'Packed byte for the ChainRot pull: the low 4 bits pick the base axis (0 +X, 1 -X, 2 +Y, 3 -Y, 4 +Z, 5 -Z), '
        'the high 4 bits the rotation order (as RotOrder).'
    ),
    'move:Distance': (
        "Where on the path the particle starts, as a distance in cm from the path's start (PathChain: along the "
        'rope). Use the random part to scatter particles along the path.'
    ),
    'move:ForceRate': (
        "Not understood yet; probably the strength of the external force chosen by ForceType. Keep the game's value."
    ),
    'move:ForceType': (
        'Not understood yet; probably selects which external force (such as wind) acts on the particles. Only the low'
        " 4 bits are read. Keep the game's value."
    ),
    'move:ForceVertexAttenuateRate': (
        'Probably how the wind strength changes from point to point along the rope (with ChainOptionFlag 0x10). Keep '
        "the game's value."
    ),
    'move:FrameInf': (
        "Fraction of each rope point's velocity kept every frame. 1 = no damping (keeps swinging), lower values calm "
        'the rope down faster.'
    ),
    'move:Gravity': (
        'How much the downward fall speed grows each frame (cm per frame, per frame). Used by Add particles and by '
        'path particles after release; negative values make them float up.'
    ),
    'move:Length': 'Total rope length in cm, split evenly between its points. Can be keyframed.',
    'move:LengthAdd': (
        "Change of the rope's total length per frame (cm); positive grows it, negative shrinks it. Ignored while "
        'Length is keyframed.'
    ),
    'move:member_0x3e': "Not understood yet; probably padding. Keep the game's value.",
    'move:member_chain_0x02': "Not used by the game's rope code; keep the game's value.",
    'move:MoveOptionFlag': (
        "Motion options (bits). 2: gravity ignores the effect's scale. 4: high accuracy, the generator tracks its own"
        " movement every frame. 8: always correct, Add/Mul particles are carried along by the generator's movement "
        '(needs bit 4 or a generator keyframe) instead of staying where they were emitted.'
    ),
    'move:MPathChain0879': "Not understood yet; keep the game's value.",
    'move:MPathChain087a': "Not understood yet; keep the game's value.",
    'move:MPathChain087b': "Not understood yet; keep the game's value.",
    'move:MPathChain327c': "Not understood yet; keep the game's value.",
    'move:Path3DScaleX': (
        'Scales the path along X. Applies to PathKeyframe offsets and PathStrip curves; rolled once each time the '
        'generator starts, so all particles of one emission share it.'
    ),
    'move:Path3DScaleY': (
        'Scales the path along Y. Applies to PathKeyframe offsets and PathStrip curves; rolled once each time the '
        'generator starts, so all particles of one emission share it.'
    ),
    'move:Path3DScaleZ': (
        'Scales the path along Z. Applies to PathKeyframe offsets and PathStrip curves; rolled once each time the '
        'generator starts, so all particles of one emission share it.'
    ),
    'move:PathCurveDivideNum': (
        'Probably how many pieces each curve segment is split into for hermite/spline paths when the game measures '
        "and samples the curve. Keep the game's value."
    ),
    'move:PathLength': (
        "PathLine only: the line's length in cm. The particle stops at the end, unless PathOptionFlag says to release"
        ' or kill it there. Scaled by PathLengthScale.'
    ),
    'move:PathLengthScale': (
        'Overall path size multiplier: scales the curve or keyframed offsets (on top of Path3DScale), the PathLength '
        'limit and the PathChain rope length. Rolled once each time the generator starts.'
    ),
    'move:PathOptionFlag': (
        'What happens at the end of the path (bits). 1: release the particle right away (otherwise it stops at the '
        "end). 2: kill the particle. 4: probably ends the life block's keep-hold, so the particle starts fading out."
    ),
    'move:PathStripFlag': (
        'Path options (bits). 0x08: loop, wrapping back to the start at the end of the curve instead of stopping. '
        '0x40 (skinning) is not understood yet.'
    ),
    'move:PathStripPartsNo': 'Which curve (part) of the .efs file to follow, counting from 0.',
    'move:PathStripPath': 'The .efs path curve the particles follow, as a game path without the extension.',
    'move:PathStripType': (
        'How the .efs curve is interpolated between its points: 1 linear, 2 hermite, 3 spline. The Blender preview '
        'always uses linear.'
    ),
    'move:PreUpdateLoopNum': (
        'Rope simulation steps run when it spawns, so it starts already settled (e.g. hanging) instead of straight. '
        'Raise it if the rope visibly swings into place on its first frames.'
    ),
    'move:ReleaseFrame': (
        'Frames the particle rides the path before it is released. Only used when ReleaseType is not 0. Can be '
        'keyframed.'
    ),
    'move:ReleaseType': (
        'How a path particle leaves the path when ReleaseFrame runs out: 0 never leaves, 1 keeps the velocity it had '
        "on the path, 2 flies off at the path's current speed (PathKeyframe: a fresh Speed). Released particles then "
        'move freely in the world with Acceleration and Gravity.'
    ),
    'move:Rot': (
        'Angles in radians (X, Y, Z) that turn the RotAxisType direction into the launch direction. Use the random '
        'part for spray: e.g. a random X and Z spread around +Y gives a cone. For path moves it rotates the whole '
        'path. Can be keyframed.'
    ),
    'move:RotAxisOrder': (
        'Packed byte: the low 4 bits are RotAxisType and the high 4 bits are RotOrder. Edit those instead.'
    ),
    'move:RotAxisType': (
        'Base direction the particles travel along before Rot is applied: 0 +X, 1 -X, 2 +Y (up), 3 -Y, 4 +Z, 5 -Z. '
        'For PathLine it is the direction of the line.'
    ),
    'move:RotOrder': (
        'Order the three Rot angles are applied in (first letter first): 0 XYZ, 1 XZY, 2 YXZ, 3 YZX, 4 ZXY, 5 ZYX. '
        'Only matters when more than one angle is non-zero.'
    ),
    'move:ShrinkCoef': "Not read by the DX9 game; keep the game's value.",
    'move:Speed': (
        'Starting speed in cm per frame along the launch direction. For path moves it is how fast the particle '
        'travels along the path (distance per frame); PathKeyframe only uses it on release. Can be keyframed.'
    ),
    'move:SpeedCoef': (
        'Mul moves only: the speed is multiplied by this every frame. Below 1 the particle slows down smoothly (drag,'
        ' e.g. 0.9), 1 keeps a constant speed, above 1 speeds it up.'
    ),
    'move:StretchScale': "Not read by the DX9 game; keep the game's value.",
    'move:VertexInf': (
        "Springiness: how much of each stretch correction is fed back into the rope's velocity. Higher values make "
        'the rope snap back and wobble more.'
    ),

    # -- collision -------------------------------------------------------------------------------------------
    'collision:BounceCallbackFlag': (
        'Probably makes the game notify the object that owns the effect on each bounce (e.g. for a sound). Keep the '
        "game's value."
    ),
    'collision:BounceEffectMode': (
        'Two 4-bit settings for the bounce effect: the high nibble picks how it is attached, the low nibble is passed'
        " to the spawned effect. Not understood yet; keep the game's value."
    ),
    'collision:BounceEffectParam': (
        "Two values handed to the bounce effect when it spawns. Not understood yet; keep the game's value."
    ),
    'collision:BounceEffectPath': (
        'Effect (.efl) spawned at the hit point on every bounce, as a game path without the extension. Leave empty '
        'for none.'
    ),
    'collision:BounceNumBase': (
        'How many times the particle bounces before CollType applies. The count is BounceNumBase plus a random '
        '0..BounceNumRange.'
    ),
    'collision:BounceNumRange': (
        'Random extra bounces: each particle gets BounceNumBase plus a random 0..BounceNumRange bounces.'
    ),
    'collision:BounceRate': (
        'Fraction of the speed kept on each bounce: 1 bounces back at full speed, 0.5 at half, 0 stops dead.'
    ),
    'collision:CollCancelFrame': (
        "Frames after spawn during which collision is ignored, so particles born inside or near geometry don't hit it"
        ' at once. The game reads this byte and member_0x3 together as one 16-bit number (this is the low byte).'
    ),
    'collision:CollFlag': (
        "Collision options (bits). Bit 0 (finish: stop animation): probably freezes the particle's flipbook animation"
        ' when it stops on a surface.'
    ),
    'collision:CollRadius': (
        'Collision radius in cm: the particle hits when it gets this close to a surface. Unlike other ranges, base is'
        ' the starting radius and base + rand is the maximum it can grow to with CollRadiusAdd.'
    ),
    'collision:CollRadiusAdd': (
        'Growth of the collision radius per frame (cm). It grows from the CollRadius base up to base + rand.'
    ),
    'collision:CollType': (
        'What happens when the particle hits the stage after its bounces are used up: 0 it dies, 1 it stops where it '
        'hit, 2 it carries on with collision turned off. The Blender preview uses a flat ground at z = 0.'
    ),
    'collision:FinishCallbackFlag': (
        "Probably makes the game notify the object that owns the effect when the collision finishes. Keep the game's "
        'value.'
    ),
    'collision:FinishEffectMode': (
        'Two 4-bit settings for the finish effect: the high nibble picks how it is attached, the low nibble is passed'
        " to the spawned effect. Not understood yet; keep the game's value."
    ),
    'collision:FinishEffectParam': (
        "Two values handed to the finish effect when it spawns. Not understood yet; keep the game's value."
    ),
    'collision:FinishEffectPath': (
        'Effect (.efl) spawned at the hit point when the collision finishes (no bounces left), as a game path without'
        ' the extension. Leave empty for none.'
    ),
    'collision:member_0x25': 'Not used by the DX9 game (padding); keep 0.',
    'collision:member_0x3': (
        'High byte of CollCancelFrame (the game reads both bytes as one number). Leave 0 unless you need more than '
        '255 frames.'
    ),

    # -- culling ---------------------------------------------------------------------------------------------
    'culling:CullingAngleEnd': (
        'Angle (radians) between the culling direction and the way to the camera where the angle fade reaches 0. '
        'Without the angle-range option the fade runs from 1 when facing straight along the direction down to 0 here.'
    ),
    'culling:CullingAngleStart': (
        'With the angle-range option (CullingOptionFlag 0x800): up to this angle (radians) the particle is fully '
        'visible; past it the fade drops by CullingRate. Needs the angle fade (CullingFlag 0x80).'
    ),
    'culling:CullingDistFarEnd': (
        'Camera distance (cm) where the particle has faded out; farther than this it is hidden. Needs CullingOptionFlag '
        '0x2000 (distance fade).'
    ),
    'culling:CullingDistFarStart': (
        'Camera distance (cm) where the particle starts fading out (or is cut off at once with CullingOptionFlag '
        '0x8000).'
    ),
    'culling:CullingDistNearEnd': (
        'Camera distance (cm) where the near fade-in is complete; between NearStart and this the particle fades in '
        '(or stays hidden with CullingOptionFlag 0x4000).'
    ),
    'culling:CullingDistNearStart': (
        'Camera distance (cm) below which the particle is hidden: closer than this to the camera it is not drawn.'
    ),
    'culling:CullingFlag': (
        "Low byte of CullingFlags, the same switches as the particle's CullingFlag: 0x4 works the fade out for each "
        'particle instead of once at the generator, 0x80 turns on the angle fade, 0x2 the occlusion test.'
    ),
    'culling:CullingFlags': (
        "Packed word, only used when the particle's CullingFlag bit 0 is on. Low byte: CullingFlag; bits 8-11: axis "
        'turned by CullingRot into the culling direction; bits 12-15: its rotation order; upper half: '
        'CullingOptionFlag. Edit the individual fields instead.'
    ),
    'culling:CullingOptionFlag': (
        'Fade options: 0x2000 distance fade (CullingDist*), 0x4000 / 0x8000 cut off at once instead of fading near / '
        'far, 0x800 angle range (fade from CullingAngleStart by CullingRate), 0x1 also accept the opposite direction, '
        '0x1000 with 0x1: both directions must pass (otherwise either one is enough).'
    ),
    'culling:CullingRate': (
        'With the angle-range option: how many radians past CullingAngleStart the fade takes to reach 0 (the files '
        'use CullingAngleEnd - CullingAngleStart).'
    ),
    'culling:CullingRot': (
        'Angles in radians that turn the axis from CullingFlags into the culling direction (it then turns with the '
        'generator). The angle fade compares it with the way to the camera.'
    ),
    'culling:CullingRotAxisType': (
        'Bits 8-11 of CullingFlags: the axis that CullingRot turns into the direction used for the angle fade (same '
        'values as RotAxisType).'
    ),
    'culling:CullingRotOrder': 'Bits 12-15 of CullingFlags: the rotation order used to apply CullingRot.',
    'culling:OcclusionRadius': (
        'Probably the radius (cm) of the sphere the game tests for being hidden behind geometry, when CullingFlags '
        "bit 2 is on. Keep the game's value."
    ),
}


def lookup(key):
    """Help text for "<slot>:<field>", or ""."""
    return HELP.get(key, "")
