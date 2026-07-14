"""Cutting-stock optimization algorithms (waste minimization).

No GUI dependency – operates only on plain tuples and the result
dataclasses defined below.

Algorithms:
  Greedy (fast):
    1D: First-Fit-Decreasing (FFD)
    2D: Best-Area-Fit guillotine packing (horizontal-first split)
  Nested Guillotine (default for panels):
    2D: like greedy, but tries both split directions per cut and keeps
    the largest contiguous free rectangle.
  GA (thorough):
    1D + 2D: genetic algorithm over part permutations (plus rotation
    flags in 2D). Typically reaches ~95%+ material utilization.

All algorithms account for the saw blade width (kerf) and per-part
grain-direction constraints (which orientations are allowed).

Conventions used throughout this module:
  - All dimensions are millimetres (like the DB).
  - A panel is laenge (x, horizontal) × breite (y, vertical),
    origin (0,0) = top-left corner.
  - Kerf: every cut destroys a `kerf` wide strip of material. When a
    part is placed into a free rectangle, the leftover rectangles start
    `kerf` beyond the part's edge, and a leftover only exists if more
    than the kerf remains (hence the recurring `... - kerf > 0` checks).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


# =====================================================================
# Result dataclasses
# =====================================================================

@dataclass
class Platzierung:
    """One placed part on a stock piece.

    laenge/breite are the ACTUAL x/y extents after rotation – consumers
    (canvas, PDF) must not swap them again when `gedreht` is set.
    """
    teil_label: str
    laenge: float
    breite: float = 0.0  # panels only
    x: float = 0.0       # position on the stock piece (panels only)
    y: float = 0.0
    gedreht: bool = False


@dataclass
class Schnittplan:
    """Cutting plan for a single stock piece (one bar or one panel)."""
    lagerstueck_id: int
    lager_laenge: float
    lager_breite: float = 0.0
    platzierungen: list[Platzierung] = field(default_factory=list)
    reste: list[tuple[float, float]] = field(default_factory=list)  # (L, W) or (L,)
    verschnitt_mm: float = 0.0       # 1D: mm, 2D: mm² (absolute waste)
    verschnitt_prozent: float = 0.0


@dataclass
class OptimierungsErgebnis:
    """Overall result of one optimization run."""
    schnittplaene: list[Schnittplan] = field(default_factory=list)
    fehlende_teile: list[str] = field(default_factory=list)  # labels that didn't fit
    gesamt_verschnitt_prozent: float = 0.0


# =====================================================================
# 1D Cutting-Stock (Stangen)
# =====================================================================

@dataclass
class StangenVorrat:
    lagerstueck_id: int
    laenge: float
    anzahl: int


def optimize_1d(
    teile: list[tuple[str, float, int]],
    vorrat: list[StangenVorrat],
    kerf: float = 3.0,
) -> OptimierungsErgebnis:
    """1D bin packing with First-Fit-Decreasing.

    Args:
        teile: list of (label, length, quantity) – expanded to single pieces.
        vorrat: available bars.
        kerf: saw blade width in mm.

    Strategy: consume short/offcut bars first (sorted ascending, so
    remnants get used up before fresh full-length bars), place parts
    longest-first (FFD) into the first bar with enough room.
    """
    einzelteile: list[tuple[str, float]] = []
    for label, laenge, anzahl in teile:
        einzelteile.extend((label, laenge) for _ in range(anzahl))
    einzelteile.sort(key=lambda t: t[1], reverse=True)

    verfuegbar: list[dict] = []
    for sv in sorted(vorrat, key=lambda s: s.laenge):
        for _ in range(sv.anzahl):
            verfuegbar.append({
                "id": sv.lagerstueck_id,
                "laenge": sv.laenge,
                "rest": sv.laenge,   # remaining usable length at the bar's end
                "platzierungen": [],
            })

    fehlend: list[str] = []

    for label, teil_laenge in einzelteile:
        platziert = False
        for stange in verfuegbar:
            # Kerf accounting: the first piece starts flush at the bar's
            # end (no cut before it), every further piece needs one kerf
            # of extra material for the cut separating it from the
            # previous piece.
            benoetigte_breite = teil_laenge
            if stange["platzierungen"]:
                benoetigte_breite += kerf
            if stange["rest"] >= benoetigte_breite:
                # Next free position = consumed length so far (+ kerf gap)
                pos = stange["laenge"] - stange["rest"]
                if stange["platzierungen"]:
                    pos += kerf
                stange["platzierungen"].append(
                    Platzierung(teil_label=label, laenge=teil_laenge, x=pos)
                )
                stange["rest"] -= benoetigte_breite
                platziert = True
                break
        if not platziert:
            fehlend.append(label)

    ergebnis = OptimierungsErgebnis(fehlende_teile=fehlend)
    gesamt_nutzbar = 0.0
    gesamt_genutzt = 0.0

    for stange in verfuegbar:
        if not stange["platzierungen"]:
            continue
        genutzt = sum(p.laenge for p in stange["platzierungen"])
        # n pieces need n-1 separating cuts; the kerf material is lost
        kerf_verlust = kerf * (len(stange["platzierungen"]) - 1)
        verschnitt = stange["laenge"] - genutzt - kerf_verlust
        plan = Schnittplan(
            lagerstueck_id=stange["id"],
            lager_laenge=stange["laenge"],
            platzierungen=stange["platzierungen"],
            reste=[(stange["rest"],)] if stange["rest"] > 0 else [],
            verschnitt_mm=verschnitt,
            verschnitt_prozent=round(verschnitt / stange["laenge"] * 100, 1)
            if stange["laenge"] > 0 else 0,
        )
        ergebnis.schnittplaene.append(plan)
        gesamt_nutzbar += stange["laenge"]
        gesamt_genutzt += genutzt

    if gesamt_nutzbar > 0:
        ergebnis.gesamt_verschnitt_prozent = round(
            (1 - gesamt_genutzt / gesamt_nutzbar) * 100, 1
        )

    return ergebnis


# =====================================================================
# 2D Guillotine-Packing (Platten)
# =====================================================================

@dataclass
class PlattenVorrat:
    lagerstueck_id: int
    laenge: float
    breite: float
    anzahl: int


@dataclass
class _Freiraum:
    """A free (still uncut) rectangular region on a panel.

    The packing algorithms maintain a list of disjoint free rectangles
    per panel; placing a part consumes one rectangle and appends up to
    two smaller ones (the guillotine split leftovers).
    """
    x: float
    y: float
    laenge: float
    breite: float

    @property
    def flaeche(self) -> float:
        return self.laenge * self.breite


def optimize_2d(
    teile: list[tuple[str, float, float, int]],
    vorrat: list[PlattenVorrat],
    kerf: float = 3.0,
    drehung_erlaubt: bool = True,
    teil_drehung: dict[str, tuple[bool, bool]] | None = None,
) -> OptimierungsErgebnis:
    """2D guillotine packing with Best-Area-Fit.

    Args:
        teile: list of (label, length, width, quantity).
        vorrat: available panels.
        kerf: saw blade width in mm.
        drehung_erlaubt: global fallback – overridden by teil_drehung.
        teil_drehung: dict label → (normal_ok, rotated_ok) per part
            (derived from grain directions). If given, it determines the
            allowed orientations.

    Guillotine constraint: every cut runs edge-to-edge through the
    current region, so all leftovers stay rectangles (cuttable on a
    panel saw).

    Best-Area-Fit: each part goes into the free rectangle that leaves
    the least wasted area (fr.area - part.area), across ALL panels and
    both orientations – a tight fit keeps big rectangles intact for the
    remaining (large) parts.
    """
    einzelteile: list[tuple[str, float, float]] = []
    for label, laenge, breite, anzahl in teile:
        einzelteile.extend((label, laenge, breite) for _ in range(anzahl))
    # Place big parts first – they are the hardest to fit
    einzelteile.sort(key=lambda t: t[1] * t[2], reverse=True)

    platten: list[dict] = []
    for pv in sorted(vorrat, key=lambda p: p.laenge * p.breite):
        for _ in range(pv.anzahl):
            platten.append({
                "id": pv.lagerstueck_id,
                "laenge": pv.laenge,
                "breite": pv.breite,
                "freiraeume": [_Freiraum(0, 0, pv.laenge, pv.breite)],
                "platzierungen": [],
            })

    fehlend: list[str] = []

    for label, t_laenge, t_breite in einzelteile:
        platziert = False
        best_platte = None
        best_freiraum_idx = None
        best_gedreht = False
        best_rest_flaeche = float("inf")

        # Determine allowed orientations for this part (grain rules)
        if teil_drehung and label in teil_drehung:
            normal_ok, gedreht_ok = teil_drehung[label]
        else:
            normal_ok, gedreht_ok = True, drehung_erlaubt
        orientierungen = []
        if normal_ok:
            orientierungen.append(False)
        if gedreht_ok:
            orientierungen.append(True)

        for platte in platten:
            for fi, fr in enumerate(platte["freiraeume"]):
                for gedreht in orientierungen:
                    tl = t_breite if gedreht else t_laenge
                    tb = t_laenge if gedreht else t_breite
                    if tl <= fr.laenge and tb <= fr.breite:
                        rest = fr.flaeche - tl * tb
                        if rest < best_rest_flaeche:
                            best_rest_flaeche = rest
                            best_platte = platte
                            best_freiraum_idx = fi
                            best_gedreht = gedreht

        if best_platte is not None:
            fr = best_platte["freiraeume"].pop(best_freiraum_idx)
            tl = t_breite if best_gedreht else t_laenge
            tb = t_laenge if best_gedreht else t_breite

            best_platte["platzierungen"].append(Platzierung(
                teil_label=label, laenge=tl, breite=tb,
                x=fr.x, y=fr.y, gedreht=best_gedreht,
            ))

            # Guillotine split, horizontal-first. The part sits in the
            # top-left corner of the consumed rectangle; the horizontal
            # cut below the part runs the FULL width, so the two
            # leftovers are:
            #
            #   +--------+--------+
            #   |  part  | right  |   right: same height as the part
            #   +--------+--------+
            #   |     below       |   below: full width of the region
            #   +-----------------+
            #
            # Each leftover starts kerf beyond the part's edge (the cut
            # itself eats that strip) and only exists if more than the
            # kerf remains.
            rest_rechts_l = fr.laenge - tl - kerf
            if rest_rechts_l > 0:
                best_platte["freiraeume"].append(_Freiraum(
                    x=fr.x + tl + kerf, y=fr.y,
                    laenge=rest_rechts_l, breite=tb,
                ))

            rest_oben_b = fr.breite - tb - kerf
            if rest_oben_b > 0:
                best_platte["freiraeume"].append(_Freiraum(
                    x=fr.x, y=fr.y + tb + kerf,
                    laenge=fr.laenge, breite=rest_oben_b,
                ))

            platziert = True

        if not platziert:
            fehlend.append(label)

    ergebnis = OptimierungsErgebnis(fehlende_teile=fehlend)
    gesamt_flaeche = 0.0
    gesamt_genutzt = 0.0

    for platte in platten:
        if not platte["platzierungen"]:
            continue
        platte_flaeche = platte["laenge"] * platte["breite"]
        genutzt = sum(p.laenge * p.breite for p in platte["platzierungen"])
        verschnitt = platte_flaeche - genutzt

        reste: list[tuple[float, float]] = []
        for fr in platte["freiraeume"]:
            if fr.laenge > 0 and fr.breite > 0:
                reste.append((fr.laenge, fr.breite))

        plan = Schnittplan(
            lagerstueck_id=platte["id"],
            lager_laenge=platte["laenge"],
            lager_breite=platte["breite"],
            platzierungen=platte["platzierungen"],
            reste=reste,
            verschnitt_mm=verschnitt,
            verschnitt_prozent=round(verschnitt / platte_flaeche * 100, 1)
            if platte_flaeche > 0 else 0,
        )
        ergebnis.schnittplaene.append(plan)
        gesamt_flaeche += platte_flaeche
        gesamt_genutzt += genutzt

    if gesamt_flaeche > 0:
        ergebnis.gesamt_verschnitt_prozent = round(
            (1 - gesamt_genutzt / gesamt_flaeche) * 100, 1
        )

    return ergebnis


# =====================================================================
# Nested Guillotine – chooses the split direction per cut (2D)
# =====================================================================

def optimize_2d_nested(
    teile: list[tuple[str, float, float, int]],
    vorrat: list[PlattenVorrat],
    kerf: float = 3.0,
    drehung_erlaubt: bool = True,
    teil_drehung: dict[str, tuple[bool, bool]] | None = None,
) -> OptimierungsErgebnis:
    """2D nested guillotine: tries both split directions per cut.

    Unlike plain guillotine packing (always horizontal-first), this
    algorithm checks for every placement whether a horizontal or a
    vertical through-cut produces the larger contiguous leftover.
    A larger single rectangle is more useful for the remaining parts
    than two smaller ones of the same total area.
    """
    einzelteile: list[tuple[str, float, float]] = []
    for label, laenge, breite, anzahl in teile:
        einzelteile.extend((label, laenge, breite) for _ in range(anzahl))
    einzelteile.sort(key=lambda t: t[1] * t[2], reverse=True)

    if not einzelteile or not vorrat:
        return optimize_2d(teile, vorrat, kerf, drehung_erlaubt, teil_drehung)

    def get_orient(label):
        if teil_drehung and label in teil_drehung:
            return teil_drehung[label]
        return True, drehung_erlaubt

    platten: list[dict] = []
    for pv in sorted(vorrat, key=lambda p: p.laenge * p.breite):
        for _ in range(pv.anzahl):
            platten.append({
                "id": pv.lagerstueck_id,
                "laenge": pv.laenge, "breite": pv.breite,
                "freiraeume": [_Freiraum(0, 0, pv.laenge, pv.breite)],
                "platzierungen": [],
            })

    fehlend: list[str] = []

    for label, t_laenge, t_breite in einzelteile:
        platziert = False
        best_platte = None
        best_fi = None
        best_gedreht = False
        best_split = "h"
        best_rest_flaeche = float("inf")
        best_max_rest = 0.0

        normal_ok, gedreht_ok = get_orient(label)

        for platte in platten:
            for fi, fr in enumerate(platte["freiraeume"]):
                for rotated in [False, True]:
                    if rotated and not gedreht_ok:
                        continue
                    if not rotated and not normal_ok:
                        continue
                    tl = t_breite if rotated else t_laenge
                    tb = t_laenge if rotated else t_breite
                    if tl > fr.laenge or tb > fr.breite:
                        continue

                    rest = fr.flaeche - tl * tb

                    for split in ["h", "v"]:
                        # Size of the two leftover rectangles for each
                        # split direction (part sits top-left, kerf is
                        # subtracted on the cut side):
                        #   "h" (horizontal through-cut below the part):
                        #     r1 = right of the part, part height only
                        #     r2 = below, full region width
                        #   "v" (vertical through-cut right of the part):
                        #     r1 = below the part, part width only
                        #     r2 = right, full region height
                        if split == "h":
                            r1 = max(0, fr.laenge - tl - kerf) * tb
                            r2 = fr.laenge * max(0, fr.breite - tb - kerf)
                        else:
                            r1 = tl * max(0, fr.breite - tb - kerf)
                            r2 = max(0, fr.laenge - tl - kerf) * fr.breite
                        max_rest = max(r1, r2)

                        # Selection: 1) least wasted area (tight fit),
                        # 2) tie-break: largest contiguous leftover block
                        if (rest < best_rest_flaeche or
                            (rest == best_rest_flaeche and
                             max_rest > best_max_rest)):
                            best_rest_flaeche = rest
                            best_max_rest = max_rest
                            best_platte = platte
                            best_fi = fi
                            best_gedreht = rotated
                            best_split = split

        if best_platte is not None:
            fr = best_platte["freiraeume"].pop(best_fi)
            tl = t_breite if best_gedreht else t_laenge
            tb = t_laenge if best_gedreht else t_breite

            best_platte["platzierungen"].append(Platzierung(
                teil_label=label, laenge=tl, breite=tb,
                x=fr.x, y=fr.y, gedreht=best_gedreht))

            if best_split == "h":
                r_l = fr.laenge - tl - kerf
                r_b = fr.breite - tb - kerf
                if r_l > 0:
                    best_platte["freiraeume"].append(
                        _Freiraum(fr.x + tl + kerf, fr.y, r_l, tb))
                if r_b > 0:
                    best_platte["freiraeume"].append(
                        _Freiraum(fr.x, fr.y + tb + kerf, fr.laenge, r_b))
            else:
                r_b = fr.breite - tb - kerf
                r_l = fr.laenge - tl - kerf
                if r_b > 0:
                    best_platte["freiraeume"].append(
                        _Freiraum(fr.x, fr.y + tb + kerf, tl, r_b))
                if r_l > 0:
                    best_platte["freiraeume"].append(
                        _Freiraum(fr.x + tl + kerf, fr.y, r_l, fr.breite))

            platziert = True

        if not platziert:
            fehlend.append(label)

    return _build_2d_result(platten, fehlend, kerf)


# =====================================================================
# Genetic algorithm (GA) – thorough optimization
# =====================================================================

_GA_POPULATION = 80
_GA_GENERATIONS = 200
_GA_MUTATION_RATE = 0.15
_GA_ELITE_RATIO = 0.1


def optimize_1d_ga(
    teile: list[tuple[str, float, int]],
    vorrat: list[StangenVorrat],
    kerf: float = 3.0,
) -> OptimierungsErgebnis:
    """1D cutting stock with a genetic algorithm.

    Chromosome = permutation of the part order; placement itself is
    deterministic first-fit per permutation, so the GA only searches
    the ordering. Fitness = total placed length. The FFD ordering is
    seeded into the initial population, so the GA can never end up
    worse than plain FFD.

    Note: random.Random(42) makes runs reproducible – two runs on the
    same input always return the same plan.
    """
    einzelteile: list[tuple[str, float]] = []
    for label, laenge, anzahl in teile:
        einzelteile.extend((label, laenge) for _ in range(anzahl))

    if not einzelteile or not vorrat:
        return optimize_1d(teile, vorrat, kerf)

    n = len(einzelteile)
    rng = random.Random(42)

    def make_stangen():
        return [{"laenge": sv.laenge, "rest": sv.laenge, "n": 0}
                for sv in sorted(vorrat, key=lambda s: s.laenge)
                for _ in range(sv.anzahl)]

    def evaluate(perm: list[int]) -> float:
        stangen = make_stangen()
        genutzt = 0.0
        for idx in perm:
            _, teil_laenge = einzelteile[idx]
            for st in stangen:
                bed = teil_laenge + (kerf if st["n"] > 0 else 0)
                if st["rest"] >= bed:
                    st["rest"] -= bed
                    st["n"] += 1
                    genutzt += teil_laenge
                    break
        return genutzt

    def crossover(p1: list[int], p2: list[int]) -> list[int]:
        # Order crossover (OX): copy a random slice from parent 1,
        # then fill the remaining slots with parent 2's genes in their
        # relative order. Keeps the child a valid permutation.
        a, b = sorted(rng.sample(range(n), 2))
        child = [-1] * n
        child[a:b] = p1[a:b]
        used = set(child[a:b])
        pos = b
        for gene in p2:
            if gene not in used:
                if pos >= n:
                    pos = 0
                child[pos] = gene
                pos += 1
                used.add(gene)
        return child

    # Seed the population with the plain FFD ordering (known-good baseline)
    ffd_order = sorted(range(n), key=lambda i: einzelteile[i][1], reverse=True)
    population = [ffd_order]
    for _ in range(_GA_POPULATION - 1):
        p = list(range(n))
        rng.shuffle(p)
        population.append(p)

    elite_count = max(2, int(_GA_POPULATION * _GA_ELITE_RATIO))

    for _ in range(_GA_GENERATIONS):
        # Elitism: the best individuals survive unchanged; parents are
        # drawn from the top third, mutation = swap two positions.
        scored = sorted([(evaluate(p), p) for p in population],
                        key=lambda x: x[0], reverse=True)
        elite = [p for _, p in scored[:elite_count]]
        top_pool = [p for _, p in scored[:max(2, _GA_POPULATION // 3)]]
        new_pop = list(elite)
        while len(new_pop) < _GA_POPULATION:
            p1, p2 = rng.choice(top_pool), rng.choice(top_pool)
            child = crossover(p1, p2)
            if rng.random() < _GA_MUTATION_RATE:
                i, j = rng.sample(range(n), 2)
                child[i], child[j] = child[j], child[i]
            new_pop.append(child)
        population = new_pop

    best = max(population, key=evaluate)

    verfuegbar: list[dict] = []
    for sv in sorted(vorrat, key=lambda s: s.laenge):
        for _ in range(sv.anzahl):
            verfuegbar.append({
                "id": sv.lagerstueck_id, "laenge": sv.laenge,
                "rest": sv.laenge, "platzierungen": [],
            })

    fehlend: list[str] = []
    for idx in best:
        label, teil_laenge = einzelteile[idx]
        placed = False
        for st in verfuegbar:
            bed = teil_laenge + (kerf if st["platzierungen"] else 0)
            if st["rest"] >= bed:
                pos = st["laenge"] - st["rest"]
                if st["platzierungen"]:
                    pos += kerf
                st["platzierungen"].append(
                    Platzierung(teil_label=label, laenge=teil_laenge, x=pos))
                st["rest"] -= bed
                placed = True
                break
        if not placed:
            fehlend.append(label)

    return _build_1d_result(verfuegbar, fehlend, kerf)


def optimize_2d_ga(
    teile: list[tuple[str, float, float, int]],
    vorrat: list[PlattenVorrat],
    kerf: float = 3.0,
    drehung_erlaubt: bool = True,
    teil_drehung: dict[str, tuple[bool, bool]] | None = None,
) -> OptimierungsErgebnis:
    """2D guillotine packing with a genetic algorithm.

    Chromosome = part permutation + one rotation flag per position.
    Placement per individual is deterministic Best-Area-Fit with the
    horizontal-first split (same rules as optimize_2d), so the GA
    searches order and rotations only. The result is compared against
    nested guillotine at the end and the better plan wins, so
    "thorough" can never be worse than the default algorithm.
    """
    einzelteile: list[tuple[str, float, float]] = []
    for label, laenge, breite, anzahl in teile:
        einzelteile.extend((label, laenge, breite) for _ in range(anzahl))

    if not einzelteile or not vorrat:
        return optimize_2d(teile, vorrat, kerf, drehung_erlaubt, teil_drehung)

    n = len(einzelteile)
    rng = random.Random(42)

    def get_orient(label):
        if teil_drehung and label in teil_drehung:
            return teil_drehung[label]
        return True, drehung_erlaubt

    def make_plates():
        return [{"laenge": pv.laenge, "breite": pv.breite,
                 "freiraeume": [_Freiraum(0, 0, pv.laenge, pv.breite)]}
                for pv in sorted(vorrat, key=lambda p: p.laenge * p.breite)
                for _ in range(pv.anzahl)]

    def evaluate(perm, rots):
        plates = make_plates()
        placed = 0
        for pos, idx in enumerate(perm):
            label, tl, tb = einzelteile[idx]
            normal_ok, gedreht_ok = get_orient(label)
            if rots[pos] and gedreht_ok:
                tl, tb = tb, tl
            elif not normal_ok and gedreht_ok:
                tl, tb = tb, tl
            for plate in plates:
                best_fi, best_rest = None, float("inf")
                for fi, fr in enumerate(plate["freiraeume"]):
                    if tl <= fr.laenge and tb <= fr.breite:
                        r = fr.flaeche - tl * tb
                        if r < best_rest:
                            best_rest, best_fi = r, fi
                if best_fi is not None:
                    fr = plate["freiraeume"].pop(best_fi)
                    rr = fr.laenge - tl - kerf
                    if rr > 0:
                        plate["freiraeume"].append(
                            _Freiraum(fr.x + tl + kerf, fr.y, rr, tb))
                    ro = fr.breite - tb - kerf
                    if ro > 0:
                        plate["freiraeume"].append(
                            _Freiraum(fr.x, fr.y + tb + kerf, fr.laenge, ro))
                    plate["_used"] = True
                    placed += 1
                    break
        # Fitness: primarily place as many parts as possible, secondarily
        # touch as little panel area as possible (fewer panels → less
        # waste; also rewards rotations that pack tighter). The 1e12
        # weight makes one extra placed part always outweigh any
        # possible area saving (panel areas are ≪ 1e12 mm²).
        used_area = sum(p["laenge"] * p["breite"]
                        for p in plates if p.get("_used"))
        return placed * 1e12 - used_area

    def crossover(p1, p2):
        a, b = sorted(rng.sample(range(n), 2))
        child = [-1] * n
        child[a:b] = p1[a:b]
        used = set(child[a:b])
        pos = b
        for gene in p2:
            if gene not in used:
                if pos >= n:
                    pos = 0
                child[pos] = gene
                pos += 1
                used.add(gene)
        return child

    area_order = sorted(range(n),
                        key=lambda i: einzelteile[i][1] * einzelteile[i][2],
                        reverse=True)
    population = [(area_order, [False] * n)]
    for _ in range(_GA_POPULATION - 1):
        p = list(range(n))
        rng.shuffle(p)
        population.append((p, [rng.random() < 0.3 for _ in range(n)]))

    elite_count = max(2, int(_GA_POPULATION * _GA_ELITE_RATIO))

    for _ in range(_GA_GENERATIONS):
        scored = sorted([(evaluate(p, r), p, r) for p, r in population],
                        key=lambda x: x[0], reverse=True)
        elite = [(p, r) for _, p, r in scored[:elite_count]]
        top = [(p, r) for _, p, r in scored[:max(2, _GA_POPULATION // 3)]]
        new_pop = list(elite)
        while len(new_pop) < _GA_POPULATION:
            p1, r1 = rng.choice(top)
            p2, r2 = rng.choice(top)
            cp = crossover(p1, p2)
            cr = [r1[k] if rng.random() < 0.5 else r2[k] for k in range(n)]
            if rng.random() < _GA_MUTATION_RATE:
                i, j = rng.sample(range(n), 2)
                cp[i], cp[j] = cp[j], cp[i]
            if rng.random() < _GA_MUTATION_RATE:
                k = rng.randint(0, n - 1)
                cr[k] = not cr[k]
            new_pop.append((cp, cr))
        population = new_pop

    best_perm, best_rots = max(population, key=lambda x: evaluate(x[0], x[1]))

    platten: list[dict] = []
    for pv in sorted(vorrat, key=lambda p: p.laenge * p.breite):
        for _ in range(pv.anzahl):
            platten.append({
                "id": pv.lagerstueck_id,
                "laenge": pv.laenge, "breite": pv.breite,
                "freiraeume": [_Freiraum(0, 0, pv.laenge, pv.breite)],
                "platzierungen": [],
            })

    fehlend: list[str] = []
    for pos, idx in enumerate(best_perm):
        label, tl, tb = einzelteile[idx]
        normal_ok, gedreht_ok = get_orient(label)
        gedreht = best_rots[pos] and gedreht_ok
        if not normal_ok and gedreht_ok:
            gedreht = True
        if gedreht:
            tl, tb = tb, tl
        best_platte, best_fi, best_rest = None, None, float("inf")
        for platte in platten:
            for fi, fr in enumerate(platte["freiraeume"]):
                if tl <= fr.laenge and tb <= fr.breite:
                    r = fr.flaeche - tl * tb
                    if r < best_rest:
                        best_rest, best_platte, best_fi = r, platte, fi
        if best_platte is not None:
            fr = best_platte["freiraeume"].pop(best_fi)
            best_platte["platzierungen"].append(Platzierung(
                teil_label=label, laenge=tl, breite=tb,
                x=fr.x, y=fr.y, gedreht=gedreht))
            rr = fr.laenge - tl - kerf
            if rr > 0:
                best_platte["freiraeume"].append(
                    _Freiraum(fr.x + tl + kerf, fr.y, rr, tb))
            ro = fr.breite - tb - kerf
            if ro > 0:
                best_platte["freiraeume"].append(
                    _Freiraum(fr.x, fr.y + tb + kerf, fr.laenge, ro))
        else:
            fehlend.append(label)

    ga_result = _build_2d_result(platten, fehlend, kerf)

    # "Thorough" must never be worse than nested guillotine: compute
    # both and return the better plan (fewer missing parts first, then
    # lower waste percentage).
    nested_result = optimize_2d_nested(
        teile, vorrat, kerf, drehung_erlaubt, teil_drehung)
    return min(
        (ga_result, nested_result),
        key=lambda r: (len(r.fehlende_teile), r.gesamt_verschnitt_prozent),
    )


# =====================================================================
# Shared result builders
# =====================================================================

def _build_1d_result(verfuegbar, fehlend, kerf):
    ergebnis = OptimierungsErgebnis(fehlende_teile=fehlend)
    gesamt_nutzbar = gesamt_genutzt = 0.0
    for st in verfuegbar:
        if not st["platzierungen"]:
            continue
        genutzt = sum(p.laenge for p in st["platzierungen"])
        kv = kerf * max(0, len(st["platzierungen"]) - 1)
        verschnitt = st["laenge"] - genutzt - kv
        ergebnis.schnittplaene.append(Schnittplan(
            lagerstueck_id=st["id"], lager_laenge=st["laenge"],
            platzierungen=st["platzierungen"],
            reste=[(st["rest"],)] if st["rest"] > 0 else [],
            verschnitt_mm=verschnitt,
            verschnitt_prozent=round(verschnitt / st["laenge"] * 100, 1)
            if st["laenge"] > 0 else 0))
        gesamt_nutzbar += st["laenge"]
        gesamt_genutzt += genutzt
    if gesamt_nutzbar > 0:
        ergebnis.gesamt_verschnitt_prozent = round(
            (1 - gesamt_genutzt / gesamt_nutzbar) * 100, 1)
    return ergebnis


def _merge_reste(freiraeume, kerf=3.0):
    """Merge adjacent leftover rectangles into larger ones.

    The packing leaves many small free rectangles behind. For booking
    remnants back into stock we prefer few LARGE pieces, so rectangles
    that line up are fused. Two rectangles merge when they have the
    same extent on one axis (within tolerance) and the gap between them
    on the other axis is at most one kerf – such a gap is just the saw
    cut between them, i.e. physically they can be kept as one piece by
    simply not making that cut.

    Runs as a fixed-point iteration: restart the pair scan after every
    merge until no more pairs fuse.
    """
    # rect = [x, y, length, width]
    rects = [[fr.x, fr.y, fr.laenge, fr.breite] for fr in freiraeume
             if fr.laenge > 0 and fr.breite > 0]
    tol = 1.0  # mm – absorbs float noise from repeated kerf arithmetic
    changed = True
    while changed:
        changed = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                # Horizontal merge: same y-position and height, side by side
                if abs(a[1] - b[1]) < tol and abs(a[3] - b[3]) < tol:
                    left, right = (a, b) if a[0] <= b[0] else (b, a)
                    gap = right[0] - (left[0] + left[2])
                    if -tol <= gap <= kerf + tol:
                        # New length spans from left edge to right edge,
                        # implicitly swallowing the kerf gap
                        rects[i] = [left[0], a[1],
                                    (right[0] + right[2]) - left[0], a[3]]
                        del rects[j]
                        changed = True
                        break
                # Vertical merge: same x-position and length, stacked
                if abs(a[0] - b[0]) < tol and abs(a[2] - b[2]) < tol:
                    top, bot = (a, b) if a[1] <= b[1] else (b, a)
                    gap = bot[1] - (top[1] + top[3])
                    if -tol <= gap <= kerf + tol:
                        rects[i] = [a[0], top[1], a[2],
                                    (bot[1] + bot[3]) - top[1]]
                        del rects[j]
                        changed = True
                        break
            if changed:
                break
    return [(r[2], r[3]) for r in rects]


def _build_2d_result(platten, fehlend, kerf=3.0):
    ergebnis = OptimierungsErgebnis(fehlende_teile=fehlend)
    gesamt_flaeche = gesamt_genutzt = 0.0
    for pl in platten:
        if not pl["platzierungen"]:
            continue
        fl = pl["laenge"] * pl["breite"]
        gen = sum(p.laenge * p.breite for p in pl["platzierungen"])
        reste = _merge_reste(pl["freiraeume"], kerf)
        ergebnis.schnittplaene.append(Schnittplan(
            lagerstueck_id=pl["id"], lager_laenge=pl["laenge"],
            lager_breite=pl["breite"], platzierungen=pl["platzierungen"],
            reste=reste, verschnitt_mm=fl - gen,
            verschnitt_prozent=round((fl - gen) / fl * 100, 1) if fl > 0 else 0))
        gesamt_flaeche += fl
        gesamt_genutzt += gen
    if gesamt_flaeche > 0:
        ergebnis.gesamt_verschnitt_prozent = round(
            (1 - gesamt_genutzt / gesamt_flaeche) * 100, 1)
    return ergebnis
