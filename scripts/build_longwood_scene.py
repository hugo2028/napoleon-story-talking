"""Construit le décor d'une pièce de Longwood (Sainte-Hélène, un soir) dans Blender, précalcule sa lumière
dans une texture (« bake ») et l'exporte en GLB pour web/decor/longwood.glb.

Inspiré des pièces de Longwood telles qu'on les visite : papier peint jaune pâle semé de petits motifs,
moulures blanches, cheminée de marbre noir sous un grand miroir doré, velours vert,
lustre de cristal à bougies, carrelage clair à médaillons. Tout est construit ici, par code : aucun modèle,
aucune photo ni texture externe. Le décor peut donc être publié avec le dépôt (contrairement au modèle
de Napoléon).

Repères (Blender, Z en haut) : Napoléon est à l'origine, pieds à z=0, tourné vers -Y (la caméra).
Le mur du fond est à y=+2.6. Dans three.js (Y en haut) : x reste x, z Blender devient y, -y Blender devient z.

Usage :
    blender -b --factory-startup -P scripts/build_longwood_scene.py -- --preview   # rendu d'aperçu (PNG)
    blender -b --factory-startup -P scripts/build_longwood_scene.py -- --bake      # bake + export GLB
Options : --size 2048 (taille de la texture), --samples 256.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "web" / "decor"
AVATAR = ROOT / "web" / "avatar" / "avatar.glb"

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
PREVIEW = "--preview" in argv
BAKE = "--bake" in argv


def _opt(name, default):
    return int(argv[argv.index(name) + 1]) if name in argv else default


SIZE = _opt("--size", 2048)
SAMPLES = _opt("--samples", 256)

# Dimensions de la pièce (m)
X0, X1 = -3.1, 3.1       # murs gauche / droit : tout le mur du fond tient dans le cadre de l'app (écran large)
Y_BACK = 2.6             # mur du fond
Y_FRONT = -12.0          # la pièce s'étend derrière la caméra (qui recule de moitié en plus sur mobile)
H = 3.4                  # hauteur sous plafond
RAIL = 0.85              # hauteur de la cimaise
WIN_X, WIN_W, WIN_Z, WIN_H = -1.75, 1.1, 0.8, 2.0      # fenêtre du mur du fond (centre x, largeur, allège, hauteur)
BOARD = (1.45, 1.55)          # centre (x, hauteur) du tableau mural (carte et lettres), ajouté par l'app
FIRE_Y = -0.4                                         # cheminée, sur le mur gauche
LUSTRE = (1.75, 1.3, 2.5)     # lustre au-dessus du bureau, hors de l'axe du titre, entier dans le cadre
DESK = (2.0, 1.85)            # bureau (centre du plateau), entier dans le cadre
CANDLE = (DESK[0] - 0.4, DESK[1] + 0.15, 1.09)   # flamme de la bougie du bureau


# ── Utilitaires ─────────────────────────────────────────────────────────────
def link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def box(name, center, size, mat, rot_z=0.0, bevel=0.0):
    """Pavé centré en `center`, de dimensions `size` (x, y, z) ; `bevel` arrondit les arêtes (m)."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    o.rotation_euler.z = rot_z
    o.data.materials.append(mat)
    if bevel:
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        mod = o.modifiers.new("biseau", "BEVEL")
        mod.width = bevel
        mod.segments = 3
    return o


def cyl(name, center, radius, depth, mat, verts=24, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=radius, depth=depth, location=center, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.data.materials.append(mat)
    return o


def cone(name, center, r1, r2, depth, mat, verts=24):
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r1, radius2=r2, depth=depth, location=center)
    o = bpy.context.active_object
    o.name = name
    o.data.materials.append(mat)
    return o


def sphere(name, center, radius, mat, scale=(1, 1, 1)):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=center, segments=10, ring_count=6)
    o = bpy.context.active_object
    o.name = name
    o.scale = scale
    o.data.materials.append(mat)
    return o


def new_material(name):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    return m, m.node_tree, m.node_tree.nodes.get("Principled BSDF")


def mix_color(nt, factor, blend="MULTIPLY"):
    """Nœud Mix en mode couleur ; renvoie (entrée A, entrée B, sortie) côté couleur
    (le nœud a aussi des entrées « A »/« B » flottantes et vectorielles portant les mêmes noms)."""
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = blend
    mix.inputs["Factor"].default_value = factor
    a, b = [i for i in mix.inputs if i.name in ("A", "B") and i.type == "RGBA"]
    out = [o for o in mix.outputs if o.name == "Result" and o.type == "RGBA"][0]
    return a, b, out


def object_coords(nt, scale=1.0):
    coord = nt.nodes.new("ShaderNodeTexCoord")
    if scale == 1.0:
        return coord.outputs["Object"]
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    return mapping.outputs["Vector"]


def material(name, color, rough=0.7, noise=0.0, noise_scale=6.0, emission=None, strength=0.0, metallic=0.0):
    """Matériau simple ; `noise` assombrit par endroits (usure, grain)."""
    m, nt, bsdf = new_material(name)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metallic
    if noise:
        tex = nt.nodes.new("ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = noise_scale
        tex.inputs["Detail"].default_value = 6
        nt.links.new(object_coords(nt), tex.inputs["Vector"])
        a, b, out = mix_color(nt, noise)
        a.default_value = (*color, 1)
        nt.links.new(tex.outputs["Fac"], b)
        nt.links.new(out, bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = (*color, 1)
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
        bsdf.inputs["Emission Strength"].default_value = strength
        # Ces surfaces brillent mais n'éclairent pas la pièce (les lampes s'en chargent) : sans cela, Cycles
        # échantillonne chaque petite pampille comme une source de lumière et le bake devient très long.
        try:
            m.cycles.emission_sampling = "NONE"
        except AttributeError:
            pass
    return m


def dots_ramp(nt, fac_socket, stops):
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = stops[0]
    els[1].position, els[1].color = stops[-1]
    for pos, col in stops[1:-1]:
        e = els.new(pos)
        e.color = col
    nt.links.new(fac_socket, ramp.inputs["Fac"])
    return ramp.outputs["Color"]


def plane_coords(nt, axes):
    """Coordonnées 2D dans un plan : (x, z) pour le mur du fond, (y, z) pour les côtés, (x, y) pour le sol."""
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(object_coords(nt), sep.inputs["Vector"])
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(sep.outputs[axes[0].upper()], comb.inputs["X"])
    nt.links.new(sep.outputs[axes[1].upper()], comb.inputs["Y"])
    return comb.outputs["Vector"]


def wallpaper_material(axes):
    """Papier peint jaune pâle semé de petits motifs verts, en quinconce (Voronoï régulier, 2D)."""
    m, nt, bsdf = new_material(f"papier_peint_{axes}")
    bsdf.inputs["Roughness"].default_value = 0.85
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.voronoi_dimensions = "2D"
    vor.inputs["Scale"].default_value = 6.0
    vor.inputs["Randomness"].default_value = 0.0
    nt.links.new(plane_coords(nt, axes), vor.inputs["Vector"])
    color = dots_ramp(nt, vor.outputs["Distance"], [
        (0.0, (0.06, 0.16, 0.12, 1)),     # motif vert
        (0.05, (0.22, 0.30, 0.20, 1)),
        (0.08, (0.52, 0.44, 0.24, 1)),    # fond jaune pâle
        (1.0, (0.52, 0.44, 0.24, 1)),
    ])
    grime = nt.nodes.new("ShaderNodeTexNoise")
    grime.inputs["Scale"].default_value = 1.5
    nt.links.new(object_coords(nt), grime.inputs["Vector"])
    a, b, out = mix_color(nt, 0.18)
    nt.links.new(color, a)
    nt.links.new(grime.outputs["Fac"], b)
    nt.links.new(out, bsdf.inputs["Base Color"])
    return m


def tiles_material():
    """Carrelage : carreaux clairs de 40 cm, chacun orné d'un médaillon sombre (anneau et cœur), joints fins."""
    m, nt, bsdf = new_material("carrelage")
    bsdf.inputs["Roughness"].default_value = 0.35
    coords = plane_coords(nt, "xy")
    vor = nt.nodes.new("ShaderNodeTexVoronoi")          # distance au centre du carreau
    vor.voronoi_dimensions = "2D"
    vor.inputs["Scale"].default_value = 2.5
    vor.inputs["Randomness"].default_value = 0.0
    nt.links.new(coords, vor.inputs["Vector"])
    cream, dark, mid = (0.52, 0.49, 0.41, 1), (0.09, 0.11, 0.11, 1), (0.25, 0.28, 0.27, 1)
    color = dots_ramp(nt, vor.outputs["Distance"], [
        (0.0, dark), (0.06, mid), (0.10, cream), (0.25, dark), (0.30, mid), (0.33, cream), (1.0, cream),
    ])
    edge = nt.nodes.new("ShaderNodeTexVoronoi")         # joints : distance au bord du carreau
    edge.voronoi_dimensions = "2D"
    edge.feature = "DISTANCE_TO_EDGE"
    edge.inputs["Scale"].default_value = 2.5
    edge.inputs["Randomness"].default_value = 0.0
    nt.links.new(coords, edge.inputs["Vector"])
    joint = dots_ramp(nt, edge.outputs["Distance"], [(0.0, (0.16, 0.15, 0.13, 1)), (0.012, (1, 1, 1, 1)),
                                                    (1.0, (1, 1, 1, 1))])
    a, b, out = mix_color(nt, 1.0)
    nt.links.new(color, a)
    nt.links.new(joint, b)
    wear = nt.nodes.new("ShaderNodeTexNoise")
    wear.inputs["Scale"].default_value = 3.0
    nt.links.new(object_coords(nt), wear.inputs["Vector"])
    a2, b2, out2 = mix_color(nt, 0.25)
    nt.links.new(out, a2)
    nt.links.new(wear.outputs["Fac"], b2)
    nt.links.new(out2, bsdf.inputs["Base Color"])
    return m


def sky_material():
    """Ciel du soir vu par la fenêtre : dégradé vertical, orangé à l'horizon, bleu nuit en haut ; mer sombre."""
    m, nt, _ = new_material("ciel")
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 2.2
    coord = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(coord.outputs["Generated"], sep.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = 0.0, (0.010, 0.018, 0.035, 1)     # mer
    els[1].position, els[1].color = 1.0, (0.020, 0.030, 0.090, 1)     # haut du ciel, nuit
    for pos, col in ((0.36, (0.03, 0.05, 0.08, 1)),    # mer près de l'horizon
                     (0.365, (0.95, 0.42, 0.14, 1)),   # horizon embrasé
                     (0.45, (0.50, 0.24, 0.20, 1)),
                     (0.62, (0.10, 0.11, 0.26, 1))):
        e = els.new(pos)
        e.color = col
    nt.links.new(sep.outputs["Y"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return m


def chess_material():
    """Damier ivoire et bois sombre, 8 × 8 cases, calé sur les UV du plateau (elles survivent à la jointure
    des objets avant le bake, contrairement aux coordonnées « Object »)."""
    m, nt, bsdf = new_material("damier")
    bsdf.inputs["Roughness"].default_value = 0.35
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "UVMap"
    checker = nt.nodes.new("ShaderNodeTexChecker")
    checker.inputs["Scale"].default_value = 8.0
    checker.inputs["Color1"].default_value = (0.72, 0.64, 0.46, 1)
    checker.inputs["Color2"].default_value = (0.06, 0.03, 0.015, 1)
    nt.links.new(uv.outputs["UV"], checker.inputs["Vector"])
    nt.links.new(checker.outputs["Color"], bsdf.inputs["Base Color"])
    return m


CHESS_SQUARE = 0.0325          # côté d'une case (m) : plateau de 26 cm


def chessboard(M, cx, cy, z, angle=0.0):
    """Échiquier posé en (cx, cy) à la hauteur z, tourné de `angle`, avec une partie en cours."""
    ca, sa = math.cos(angle), math.sin(angle)

    def at(i, j, dz):
        """Centre de la case (i colonne, j rangée), de 0 à 7."""
        u, v = (i - 3.5) * CHESS_SQUARE, (j - 3.5) * CHESS_SQUARE
        return (cx + u * ca - v * sa, cy + u * sa + v * ca, z + dz)

    box("echiquier_cadre", (cx, cy, z + 0.006), (8 * CHESS_SQUARE + 0.03, 8 * CHESS_SQUARE + 0.03, 0.012),
        M["acajou"], rot_z=angle, bevel=0.003)
    bpy.ops.mesh.primitive_plane_add(size=1, location=(cx, cy, z + 0.0125), rotation=(0, 0, angle))
    board = bpy.context.active_object                          # plan : UV de 0 à 1 sur tout le plateau
    board.name = "echiquier"
    board.scale = (8 * CHESS_SQUARE, 8 * CHESS_SQUARE, 1)
    board.data.materials.append(M["damier"])
    top = 0.0125
    # (colonne, rangée, pièce) : milieu de partie, une dizaine de pièces de chaque camp
    white = [(4, 0, "roi"), (3, 0, "dame"), (0, 0, "tour"), (5, 2, "fou"), (2, 3, "cavalier"),
             (3, 3, "pion"), (4, 3, "pion"), (5, 1, "pion"), (6, 1, "pion"), (1, 1, "pion")]
    black = [(4, 7, "roi"), (2, 5, "dame"), (7, 7, "tour"), (2, 6, "fou"), (5, 5, "cavalier"),
             (3, 4, "pion"), (4, 5, "pion"), (5, 6, "pion"), (6, 6, "pion"), (0, 6, "pion")]
    heights = {"roi": 0.055, "dame": 0.05, "tour": 0.032, "fou": 0.04, "cavalier": 0.036, "pion": 0.026}
    for side, pieces, mat in (("b", white, M["ivoire"]), ("n", black, M["ebene"])):
        for k, (i, j, kind) in enumerate(pieces):
            h = heights[kind]
            x, y, zz = at(i, j, top)
            r = 0.0095 if kind != "pion" else 0.008
            cyl(f"piece_{side}{k}_socle", (x, y, zz + 0.004), r, 0.008, mat, verts=10)
            cone(f"piece_{side}{k}_corps", (x, y, zz + 0.008 + (h - 0.016) / 2), r * 0.8, r * 0.35, h - 0.016, mat,
                 verts=10)
            sphere(f"piece_{side}{k}_tete", (x, y, zz + h - 0.006), r * (0.75 if kind in ("roi", "dame") else 0.6), mat)
            if kind == "roi":                                  # petite croix
                box(f"piece_{side}{k}_croix", (x, y, zz + h + 0.004), (0.003, 0.003, 0.01), mat)


def drape(name, center, width, height, mat, folds=32, depth=0.05, swag=0.0):
    """Tenture plissée (plan subdivisé, plis verticaux ; `swag` creuse le bas en feston)."""
    bpy.ops.mesh.primitive_plane_add(size=1, location=center, rotation=(math.pi / 2, 0, 0))
    c = bpy.context.active_object
    c.name = name
    c.scale = (width, height, 1)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=24)
    bpy.ops.object.mode_set(mode="OBJECT")
    for v in c.data.vertices:
        v.co.z += depth * math.sin(v.co.x * folds)          # plis (z local = profondeur, le plan est debout)
        if swag:
            u = v.co.x / width * 2                          # -1 … 1
            if v.co.y < 0:                                  # bas de la tenture
                v.co.y += swag * (1 - u * u)
    c.data.materials.append(mat)
    solid = c.modifiers.new("epaisseur", "SOLIDIFY")
    solid.thickness = 0.015
    return c


# ── Construction ────────────────────────────────────────────────────────────
def build():
    M = {
        "carrelage": tiles_material(),
        "papier_peint": wallpaper_material("xz"),
        "papier_peint_cote": wallpaper_material("yz"),
        "blanc": material("blanc", (0.78, 0.76, 0.70), rough=0.5, noise=0.08, noise_scale=3),
        "plafond": material("plafond", (0.80, 0.78, 0.72), rough=0.95, noise=0.12, noise_scale=2),
        "marbre_noir": material("marbre_noir", (0.025, 0.024, 0.024), rough=0.15, noise=0.3, noise_scale=5),
        "suie": material("suie", (0.012, 0.01, 0.008), rough=0.9),
        "braises": material("braises", (0.05, 0.02, 0.01), emission=(1.0, 0.35, 0.08), strength=8.0,
                            noise=0.6, noise_scale=8),
        "velours": material("velours", (0.012, 0.075, 0.035), rough=0.9, noise=0.35, noise_scale=12),
        "acajou": material("acajou", (0.12, 0.045, 0.02), rough=0.3, noise=0.3, noise_scale=14),
        "dore": material("dore", (0.55, 0.38, 0.12), rough=0.3),
        # cristal : léger éclat propre, sinon ces fils très fins sortent sombres de la texture précalculée
        "cristal": material("cristal", (0.75, 0.75, 0.72), rough=0.1, emission=(1.0, 0.9, 0.75), strength=0.6),
        "miroir": material("miroir", (0.10, 0.10, 0.09), rough=0.08),
        "papier": material("papier", (0.80, 0.74, 0.60), rough=0.9, noise=0.15, noise_scale=20),
        "cuir": material("cuir", (0.06, 0.10, 0.05), rough=0.6),
        "livre_rouge": material("livre_rouge", (0.25, 0.05, 0.04), rough=0.6),
        "livre_brun": material("livre_brun", (0.20, 0.12, 0.06), rough=0.6),
        "cire": material("cire", (0.85, 0.80, 0.65), rough=0.5),
        "damier": chess_material(),
        "ivoire": material("ivoire", (0.82, 0.77, 0.62), rough=0.3),
        "ebene": material("ebene", (0.03, 0.022, 0.018), rough=0.3),
        "flamme": material("flamme", (1, 0.7, 0.3), emission=(1.0, 0.62, 0.25), strength=40.0),
        "vitre_bois": material("vitre_bois", (0.70, 0.68, 0.62), rough=0.6),
        "ciel": sky_material(),
    }

    W = X1 - X0
    D = Y_BACK - Y_FRONT
    YM = (Y_BACK + Y_FRONT) / 2
    t = 0.1   # épaisseur des murs

    # Sol carrelé et plafond avec corniche
    box("sol", (0, YM, -0.05), (W, D, 0.1), M["carrelage"])
    box("plafond", (0, YM, H + 0.05), (W, D, 0.1), M["plafond"])

    # Mur du fond, en morceaux autour de la fenêtre (à droite, le tableau mural est ajouté par l'app)
    wl, wr = WIN_X - WIN_W / 2, WIN_X + WIN_W / 2
    wb, wt = WIN_Z, WIN_Z + WIN_H
    yb = Y_BACK + t / 2
    pp = M["papier_peint"]
    box("fond_gauche", ((X0 + wl) / 2, yb, H / 2), (wl - X0, t, H), pp)
    box("fond_droite", ((wr + X1) / 2, yb, H / 2), (X1 - wr, t, H), pp)
    box("fond_allege", (WIN_X, yb, wb / 2), (WIN_W, t, wb), pp)
    box("fond_linteau", (WIN_X, yb, (wt + H) / 2), (WIN_W, t, H - wt), pp)
    box("mur_gauche", (X0 - t / 2, YM, H / 2), (t, D, H), M["papier_peint_cote"])
    box("mur_droit", (X1 + t / 2, YM, H / 2), (t, D, H), M["papier_peint_cote"])

    # Moulures blanches : corniche, cimaise, plinthe (fond et côtés)
    def mouldings_back(x_from, x_to, tag):
        if x_to - x_from < 0.05:
            return
        cx, w = (x_from + x_to) / 2, x_to - x_from
        box(f"cimaise_{tag}", (cx, Y_BACK - 0.02, RAIL), (w, 0.04, 0.05), M["blanc"])
        box(f"plinthe_{tag}", (cx, Y_BACK - 0.02, 0.08), (w, 0.04, 0.16), M["blanc"])
    mouldings_back(X0, wl - 0.1, "a")
    mouldings_back(wr + 0.1, X1, "b")
    box("corniche_fond", (0, Y_BACK - 0.08, H - 0.1), (W, 0.16, 0.2), M["blanc"])
    box("corniche_fond_2", (0, Y_BACK - 0.16, H - 0.03), (W, 0.12, 0.06), M["blanc"])
    for side, x, s in (("g", X0, 1), ("d", X1, -1)):
        box(f"cimaise_{side}", (x + s * 0.02, YM, RAIL), (0.04, D, 0.05), M["blanc"])
        box(f"plinthe_{side}", (x + s * 0.02, YM, 0.08), (0.04, D, 0.16), M["blanc"])
        box(f"corniche_{side}", (x + s * 0.08, YM, H - 0.1), (0.16, D, 0.2), M["blanc"])
        box(f"corniche_{side}_2", (x + s * 0.16, YM, H - 0.03), (0.12, D, 0.06), M["blanc"])

    # Fenêtre : embrasure blanche, petits bois, ciel ; draperie de velours vert en feston
    depth = 0.35
    box("appui", (WIN_X, Y_BACK + depth / 2 - 0.05, wb - 0.03), (WIN_W + 0.2, depth + 0.1, 0.06), M["blanc"])
    box("ebrasement_g", (wl - 0.03, Y_BACK + depth / 2, (wb + wt) / 2), (0.06, depth, WIN_H), M["blanc"])
    box("ebrasement_d", (wr + 0.03, Y_BACK + depth / 2, (wb + wt) / 2), (0.06, depth, WIN_H), M["blanc"])
    box("ebrasement_h", (WIN_X, Y_BACK + depth / 2, wt + 0.03), (WIN_W + 0.12, depth, 0.06), M["blanc"])
    yf = Y_BACK + depth * 0.6
    box("dormant_mil", (WIN_X, yf, (wb + wt) / 2), (0.05, 0.05, WIN_H), M["vitre_bois"])
    for k in range(1, 4):
        box(f"traverse_{k}", (WIN_X, yf, wb + WIN_H * k / 4), (WIN_W, 0.035, 0.035), M["vitre_bois"])
    for k in (1, 3):
        box(f"petit_bois_{k}", (wl + WIN_W * k / 4, yf, (wb + wt) / 2), (0.03, 0.03, WIN_H), M["vitre_bois"])
    bpy.ops.mesh.primitive_plane_add(size=1, location=(WIN_X, Y_BACK + 2.5, wb + WIN_H / 2 + 0.2),
                                     rotation=(math.pi / 2, 0, 0))
    sky = bpy.context.active_object
    sky.name = "ciel"
    sky.scale = (6.0, 4.2, 1)
    sky.data.materials.append(M["ciel"])
    drape("lambrequin", (WIN_X, Y_BACK - 0.14, wt + 0.12), WIN_W + 0.7, 0.55, M["velours"], folds=22, swag=0.18)
    drape("tenture_g", (wl - 0.22, Y_BACK - 0.12, (wt + 0.3) / 2), 0.42, wt + 0.3, M["velours"])
    drape("tenture_d", (wr + 0.22, Y_BACK - 0.12, (wt + 0.3) / 2), 0.42, wt + 0.3, M["velours"])
    box("tringle", (WIN_X, Y_BACK - 0.16, wt + 0.38), (WIN_W + 0.9, 0.04, 0.04), M["dore"])


    # Cheminée de marbre noir et grand miroir doré, sur le mur gauche
    fx = X0 + 0.18
    box("chem_jambage_av", (fx, FIRE_Y - 0.62, 0.55), (0.3, 0.18, 1.1), M["marbre_noir"])
    box("chem_jambage_ar", (fx, FIRE_Y + 0.62, 0.55), (0.3, 0.18, 1.1), M["marbre_noir"])
    box("chem_linteau", (fx, FIRE_Y, 0.98), (0.3, 1.42, 0.24), M["marbre_noir"])
    box("chem_tablette", (fx + 0.04, FIRE_Y, 1.13), (0.42, 1.65, 0.06), M["marbre_noir"])
    box("chem_foyer", (X0 + 0.05, FIRE_Y, 0.45), (0.1, 1.1, 0.9), M["suie"])
    box("chem_atre", (fx + 0.07, FIRE_Y, 0.02), (0.5, 1.55, 0.04), M["marbre_noir"])
    for k, (dy, dz) in enumerate(((-0.15, 0.08), (0.12, 0.1), (0.0, 0.16))):
        cyl(f"buche_{k}", (X0 + 0.3, FIRE_Y + dy, dz), 0.07, 0.6, M["braises"], verts=12, rot=(0, math.pi / 2, 0.3 * k))
    box("miroir_cadre", (X0 + 0.03, FIRE_Y, 2.15), (0.05, 1.15, 1.75), M["dore"])
    box("miroir", (X0 + 0.06, FIRE_Y, 2.15), (0.02, 1.0, 1.6), M["miroir"])
    box("pendule", (fx + 0.04, FIRE_Y, 1.3), (0.16, 0.34, 0.28), M["dore"])
    for dy in (-0.55, 0.55):
        cyl(f"chem_bougeoir_{dy}", (fx + 0.04, FIRE_Y + dy, 1.26), 0.02, 0.2, M["dore"], verts=10)

    # Commode d'acajou dans le coin gauche du mur du fond, buste et chandeliers dessus
    kx, ky = (X0 + WIN_X - WIN_W / 2) / 2 - 0.05, Y_BACK - 0.3
    kw = (WIN_X - WIN_W / 2) - X0 - 0.45
    box("commode", (kx, ky, 0.45), (kw, 0.5, 0.86), M["acajou"], bevel=0.01)
    box("commode_plateau", (kx, ky - 0.01, 0.9), (kw + 0.06, 0.54, 0.04), M["marbre_noir"])
    for z in (0.22, 0.48, 0.74):
        box(f"commode_tiroir_{z}", (kx, ky - 0.255, z), (kw - 0.08, 0.01, 0.2), M["acajou"])
        sphere(f"commode_bouton_{z}", (kx, ky - 0.265, z), 0.015, M["dore"])
    cyl("buste_socle", (kx, ky, 0.97), 0.07, 0.1, M["marbre_noir"])
    cone("buste_epaules", (kx, ky, 1.07), 0.04, 0.12, 0.1, M["blanc"], verts=20)
    sphere("buste", (kx, ky, 1.2), 0.065, M["blanc"], scale=(1, 0.9, 1.25))
    for k, ox in enumerate((-kw / 2 + 0.08, kw / 2 - 0.08)):
        cyl(f"commode_chandelier_{k}", (kx + ox, ky - 0.05, 1.03), 0.02, 0.22, M["dore"], verts=10)

    # Guéridon à gauche de Napoléon, avec une partie d'échecs en cours (il jouait à Longwood avec Bertrand
    # et Montholon)
    gx, gy = -1.35, 0.9
    cyl("gueridon_plateau", (gx, gy, 0.74), 0.3, 0.035, M["acajou"], verts=32)
    cyl("gueridon_pied", (gx, gy, 0.37), 0.03, 0.72, M["acajou"], verts=10)
    cyl("gueridon_base", (gx, gy, 0.03), 0.18, 0.05, M["acajou"], verts=20)
    chessboard(M, gx, gy, 0.7575, angle=math.radians(20))

    # Bureau d'acajou à droite, papiers, livres, bougeoir, pendule
    dx, dy = DESK
    box("bureau_plateau", (dx, dy, 0.76), (1.1, 0.6, 0.05), M["acajou"], bevel=0.012)
    box("bureau_sous_main", (dx, dy - 0.02, 0.787), (0.6, 0.38, 0.005), M["cuir"])
    box("bureau_ceinture", (dx, dy, 0.68), (1.02, 0.54, 0.12), M["acajou"])
    for ox in (-0.48, 0.48):
        for oy in (-0.23, 0.23):
            cyl(f"pied_{ox}_{oy}", (dx + ox, dy + oy, 0.31), 0.028, 0.62, M["acajou"], verts=10)
    for k, (ox, oy, rz) in enumerate(((-0.2, -0.05, 0.1), (0.0, 0.02, -0.15), (0.15, -0.08, 0.3))):
        box(f"feuille_{k}", (dx + ox, dy + oy, 0.792 + 0.002 * k), (0.21, 0.29, 0.002), M["papier"], rot_z=rz)
    for k, (h, mat) in enumerate(((0.06, "livre_rouge"), (0.07, "livre_brun"))):
        box(f"livre_{k}", (dx + 0.36, dy + 0.1, 0.785 + 0.065 * k + h / 2 - 0.02), (0.26, 0.19, h), M[mat],
            rot_z=0.08 * (k - 1))
    cyl("encrier", (dx + 0.18, dy + 0.17, 0.82), 0.035, 0.06, M["dore"])
    cx, cy = CANDLE[0], CANDLE[1]
    cyl("bougeoir_pied", (cx, cy, 0.795), 0.06, 0.02, M["dore"])
    cyl("bougeoir_tige", (cx, cy, 0.86), 0.012, 0.12, M["dore"])
    cyl("bougie", (cx, cy, 1.0), 0.018, 0.14, M["cire"], verts=12)
    sphere("flamme", (cx, cy, 1.09), 0.012, M["flamme"], scale=(1, 1, 2.2))
    # Fauteuil Empire : acajou et velours vert, derrière le bureau, tourné vers la pièce
    ch_x, ch_y, ang = dx + 0.05, dy + 0.5, math.radians(180)

    def rot_pt(px, py):
        return (ch_x + px * math.cos(ang) - py * math.sin(ang), ch_y + px * math.sin(ang) + py * math.cos(ang))
    box("fauteuil_assise", (ch_x, ch_y, 0.45), (0.5, 0.46, 0.08), M["velours"], rot_z=ang, bevel=0.03)
    box("fauteuil_dossier", (*rot_pt(0, 0.21), 0.8), (0.46, 0.05, 0.6), M["velours"], rot_z=ang, bevel=0.02)
    box("fauteuil_dossier_bois", (*rot_pt(0, 0.24), 0.8), (0.5, 0.03, 0.66), M["acajou"], rot_z=ang)
    for px in (-0.24, 0.24):
        box(f"fauteuil_accoudoir_{px}", (*rot_pt(px, 0), 0.65), (0.05, 0.42, 0.04), M["acajou"], rot_z=ang)
        for py in (-0.2, 0.2):
            cyl(f"fauteuil_pied_{px}_{py}", (*rot_pt(px, py), 0.21), 0.022, 0.42, M["acajou"], verts=8)

    # Lustre de cristal à bougies, devant le mur du fond, au-dessus de la pièce
    lx, ly, lz = LUSTRE
    cyl("lustre_tige", (lx, ly, (lz + H) / 2 + 0.2), 0.012, H - lz - 0.2, M["dore"], verts=8)
    # Pampilles : rangs de fils de cristal tendus en cône au-dessus de la couronne, gouttes et coupe dessous
    for tier, (r_top, r_bot, z_top, z_bot, n) in enumerate(((0.06, 0.30, lz + 0.5, lz - 0.02, 28),
                                                         (0.04, 0.18, lz + 0.42, lz + 0.05, 18))):
        for k in range(n):
            a = (k + 0.5 * tier) / n * math.tau
            x0, y0 = lx + r_top * math.cos(a), ly + r_top * math.sin(a)
            x1, y1 = lx + r_bot * math.cos(a), ly + r_bot * math.sin(a)
            length = math.dist((x0, y0, z_top), (x1, y1, z_bot))
            o = cyl(f"pampille_{tier}_{k}", ((x0 + x1) / 2, (y0 + y1) / 2, (z_top + z_bot) / 2), 0.006, length,
                    M["cristal"], verts=5)
            o.rotation_mode = "QUATERNION"
            o.rotation_quaternion = Vector((x0 - x1, y0 - y1, z_top - z_bot)).to_track_quat("Z", "Y")
    for k in range(20):
        a = k / 20 * math.tau
        sphere(f"goutte_{k}", (lx + 0.29 * math.cos(a), ly + 0.29 * math.sin(a), lz - 0.16), 0.014, M["cristal"],
               scale=(1, 1, 1.6))
    cone("lustre_coupe", (lx, ly, lz - 0.2), 0.03, 0.14, 0.2, M["dore"], verts=24)
    sphere("lustre_boule", (lx, ly, lz - 0.33), 0.035, M["cristal"])
    bpy.ops.mesh.primitive_torus_add(location=(lx, ly, lz - 0.08), major_radius=0.3, minor_radius=0.015)
    ring = bpy.context.active_object
    ring.name = "lustre_couronne"
    ring.data.materials.append(M["dore"])
    for k in range(8):
        a = k / 8 * math.tau
        px, py = lx + 0.3 * math.cos(a), ly + 0.3 * math.sin(a)
        cyl(f"lustre_bougie_{k}", (px, py, lz + 0.0), 0.012, 0.1, M["cire"], verts=8)
        sphere(f"lustre_flamme_{k}", (px, py, lz + 0.07), 0.01, M["flamme"], scale=(1, 1, 2.2))

    # Échelle figée : les textures (coordonnées « Object ») gardent des dimensions réelles, en mètres
    bpy.ops.object.select_all(action="DESELECT")
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o.name != "ciel":
            o.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return M


def lights():
    scn = bpy.context.scene
    world = bpy.data.worlds.new("monde")
    scn.world = world
    try:
        world.use_nodes = True
    except Exception:
        pass
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.004, 0.005, 0.008, 1)

    def add(name, kind, loc, energy, color, rot=(0, 0, 0), size=None, radius=None):
        d = bpy.data.lights.new(name, kind)
        d.energy = energy
        d.color = color
        if size is not None:
            d.shape = "RECTANGLE"
            d.size, d.size_y = size
        if radius is not None:
            d.shadow_soft_size = radius
        o = bpy.data.objects.new(name, d)
        o.location = loc
        o.rotation_euler = rot
        return link(o)

    # Jour finissant par la fenêtre (froid), feu de cheminée (chaud, à gauche), lustre et bougie (chauds)
    add("fenetre", "AREA", (WIN_X, Y_BACK + 0.25, WIN_Z + WIN_H / 2), 70, (0.62, 0.70, 1.0),
        rot=(math.radians(-90), 0, 0), size=(WIN_W, WIN_H))
    add("feu", "AREA", (X0 + 0.35, FIRE_Y, 0.35), 240, (1.0, 0.45, 0.15),
        rot=(0, math.radians(90), 0), size=(0.9, 0.5))
    add("feu_lueur", "POINT", (X0 + 0.6, FIRE_Y, 0.4), 50, (1.0, 0.5, 0.2), radius=0.3)
    add("lustre", "POINT", (LUSTRE[0], LUSTRE[1], LUSTRE[2] - 0.03), 110, (1.0, 0.68, 0.36), radius=0.25)
    add("bougie", "POINT", (CANDLE[0], CANDLE[1], CANDLE[2] + 0.01), 12, (1.0, 0.66, 0.3), radius=0.02)
    add("ambiance", "AREA", (0, -2.0, H - 0.3), 3, (1.0, 0.85, 0.65), size=(4, 4))


def anchors():
    """Repères (objets vides) exportés dans le GLB, lus par web/src/avatar.js : lustre, bougie du bureau,
    feu de cheminée, centre du ciel derrière la fenêtre. L'app suit ainsi la disposition sans coordonnées
    recopiées à la main."""
    points = {
        "ancre_lustre": LUSTRE,
        "ancre_bougie": CANDLE,
        "ancre_feu": (X0 + 0.3, FIRE_Y, 0.5),
        "ancre_ciel": (WIN_X, Y_BACK + 2.5, WIN_Z + WIN_H / 2 + 0.2),
        "ancre_tableau": (BOARD[0], Y_BACK - 0.02, BOARD[1]),
    }
    out = []
    for name, loc in points.items():
        o = bpy.data.objects.new(name, None)
        o.location = loc
        out.append(link(o))
    return out


def shadow_proxy():
    """Silhouette invisible de Napoléon : elle porte son ombre sur le sol précalculé."""
    o = cyl("ombre_napoleon", (0.03, -0.02, 0.85), 0.24, 1.7, bpy.data.materials.new("proxy"), verts=16)
    o.visible_camera = False
    return o


def camera():
    """Caméra équivalente à celle de three.js (plan par défaut, écran large)."""
    cam_data = bpy.data.cameras.new("camera")
    cam_data.sensor_fit = "VERTICAL"
    cam_data.angle_y = math.radians(30)
    cam = bpy.data.objects.new("camera", cam_data)
    cam.location = (0, -5.4, 1.28)          # comme l'app : Napoléon cadré en pied (web/src/avatar.js)
    cam.rotation_euler = (math.radians(90), 0, 0)
    link(cam)
    bpy.context.scene.camera = cam
    return cam


def cycles(samples):
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = samples
    scn.cycles.use_denoising = True
    scn.view_settings.view_transform = "AgX"
    scn.view_settings.exposure = -0.3


def preview():
    shadow_proxy().hide_render = True
    bpy.ops.import_scene.gltf(filepath=str(AVATAR))
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o.name.lower().startswith("icosphere"):
            o.hide_render = True
    camera()
    cycles(min(SAMPLES, 96))
    scn = bpy.context.scene
    scn.render.resolution_x, scn.render.resolution_y = 1150, 780   # panneau de l'avatar sur ordinateur
    out = OUT_DIR / "longwood_preview.png"
    scn.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    print("APERCU", out)


def drop_hidden_faces(obj):
    """Supprime les faces jamais vues depuis la pièce (dos des murs, dessous du sol, dessus du plafond) :
    elles occuperaient près de la moitié de la texture précalculée."""
    import bmesh
    eps = 1e-3
    wl, wr = WIN_X - WIN_W / 2, WIN_X + WIN_W / 2

    def visible(c):
        if not (X0 - eps <= c.x <= X1 + eps and -eps <= c.z <= H + eps and c.y >= Y_FRONT - eps):
            return False
        if c.y <= Y_BACK + eps:
            return True
        # Derrière le mur du fond : seulement l'embrasure de la fenêtre
        return wl - 0.1 <= c.x <= wr + 0.1 and WIN_Z - 0.1 <= c.z <= WIN_Z + WIN_H + 0.1 and c.y <= Y_BACK + 0.5

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    hidden = [f for f in bm.faces if not visible(f.calc_center_median())]
    bmesh.ops.delete(bm, geom=hidden, context="FACES")
    bm.to_mesh(obj.data)
    bm.free()
    print(f"FACES cachées supprimées : {len(hidden)}")


def bake():
    scn = bpy.context.scene
    shadow_proxy()
    camera()
    cycles(SAMPLES)
    # Le ciel n'est pas précalculé : son dégradé dépend de ses propres coordonnées, que la jointure fausserait.
    # three.js le dessine derrière la fenêtre (web/src/avatar.js) ; la lumière du soir qui entre dans la pièce
    # vient de la source « fenetre », le ciel peut donc être retiré avant le bake.
    bpy.data.objects.remove(bpy.data.objects["ciel"], do_unlink=True)
    # Tous les éléments du décor en un seul objet, avec une seconde UV « Lightmap » sans chevauchement
    deco = [o for o in scn.objects if o.type == "MESH" and o.name != "ombre_napoleon"]
    bpy.ops.object.select_all(action="DESELECT")
    for o in deco:
        o.select_set(True)
    bpy.context.view_layer.objects.active = deco[0]
    bpy.ops.object.convert(target="MESH")          # applique les modificateurs (tentures)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bpy.ops.object.join()
    room = bpy.context.active_object
    room.name = "longwood"
    room.data.transform(room.matrix_world)          # sommets en coordonnées du monde, objet à l'origine
    room.matrix_world.identity()
    drop_hidden_faces(room)
    uv = room.data.uv_layers.new(name="Lightmap")
    room.data.uv_layers.active = uv
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.002, area_weight=0.0)
    bpy.ops.uv.pack_islands(margin=0.002)
    bpy.ops.object.mode_set(mode="OBJECT")

    img = bpy.data.images.new("longwood_lumiere", SIZE, SIZE, float_buffer=True)
    for slot in room.material_slots:
        nt = slot.material.node_tree
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = img
        uvn = nt.nodes.new("ShaderNodeUVMap")
        uvn.uv_map = "Lightmap"
        nt.links.new(uvn.outputs["UV"], node.inputs["Vector"])
        nt.nodes.active = node
    cfg = scn.render.bake
    cfg.use_pass_direct = True
    cfg.use_pass_indirect = True
    cfg.use_pass_diffuse = True
    cfg.use_pass_emit = True
    cfg.use_pass_glossy = False
    cfg.use_pass_transmission = False
    cfg.margin = 6
    bpy.ops.object.select_all(action="DESELECT")
    room.select_set(True)
    bpy.context.view_layer.objects.active = room
    print(f"BAKE {SIZE}px, {SAMPLES} échantillons…", flush=True)
    bpy.ops.object.bake(type="COMBINED")

    # Version affichable (transformation AgX + exposition de la scène), lue par three.js telle quelle
    png = OUT_DIR / "longwood_lumiere.png"
    img.save_render(str(png), scene=scn)
    print("TEXTURE", png)

    # Pour l'export : un seul matériau, la texture précalculée sur l'UV Lightmap
    shown = bpy.data.images.load(str(png))
    final, nt, bsdf = new_material("longwood")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = shown
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    room.data.materials.clear()
    room.data.materials.append(final)
    for layer in [l for l in room.data.uv_layers if l.name != "Lightmap"]:
        room.data.uv_layers.remove(layer)

    bpy.ops.object.select_all(action="DESELECT")
    room.select_set(True)
    for anchor in anchors():
        anchor.select_set(True)
    glb = OUT_DIR / "longwood.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb), use_selection=True, export_format="GLB",
                              export_image_format="JPEG", export_jpeg_quality=88,
                              export_normals=False, export_materials="EXPORT", export_apply=True)
    print("GLB", glb, glb.stat().st_size)


bpy.ops.wm.read_factory_settings(use_empty=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)
build()
lights()
if PREVIEW:
    preview()
if BAKE:
    bake()
