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

import bisect
import random
import time
from dataclasses import dataclass, field

try:
    import numpy as np
    from scipy.optimize import milp, LinearConstraint, Bounds
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


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
    stueck_nr: int = 0
    platzierungen: list[Platzierung] = field(default_factory=list)
    reste: list[tuple[float, float]] = field(default_factory=list)  # 2D: (L, W), 1D: (L, x)
    verschnitt_mm: float = 0.0       # 1D: mm, 2D: mm² (absolute waste)
    verschnitt_prozent: float = 0.0
    defekte: list = field(default_factory=list)  # Defekt objects, for the PDF


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
    defekte: dict[int, dict[int, list]] | None = None,
) -> OptimierungsErgebnis:
    """1D cutting-stock optimization (pattern-based, ILP-optimal).

    Uses a two-phase approach:
      1. Pattern enumeration – find all feasible cutting patterns
         (combinations of parts) for each distinct bar length.
      2. ILP (Integer Linear Programming) via scipy – select the
         optimal set of patterns that minimizes total bars used.
         Falls back to greedy selection if scipy is unavailable.
      3. Assign labels to the chosen patterns and build Schnittplan.

    Falls back to Best-Fit-Decreasing for any remaining demand and
    for problems with defects (which create variable-length segments).
    """
    has_defects = defekte and any(
        any(dl for dl in dm.values()) for dm in defekte.values())

    if has_defects:
        return _optimize_1d_bfd(teile, vorrat, kerf, defekte)

    demand: dict[float, int] = {}
    labels_by_len: dict[float, list[str]] = {}
    for label, laenge, anzahl in teile:
        demand[laenge] = demand.get(laenge, 0) + anzahl
        labels_by_len.setdefault(laenge, []).extend([label] * anzahl)

    if not demand:
        return OptimierungsErgebnis()

    distinct_lengths = sorted(demand.keys(), reverse=True)

    bar_types: dict[float, list[StangenVorrat]] = {}
    for sv in vorrat:
        bar_types.setdefault(sv.laenge, []).append(sv)

    all_patterns: list[tuple[float, dict[float, int], float]] = []
    for bar_len in bar_types:
        patterns = _enumerate_patterns(bar_len, distinct_lengths, kerf)
        for pat in patterns:
            used = sum(l * c for l, c in pat.items())
            cuts = sum(pat.values())
            total_used = used + kerf * max(0, cuts - 1)
            all_patterns.append((bar_len, pat, total_used / bar_len))

    remaining = dict(demand)
    bar_counts: dict[float, int] = {}
    for sv in vorrat:
        bar_counts[sv.laenge] = bar_counts.get(sv.laenge, 0) + sv.anzahl

    selected: list[tuple[float, dict[float, int]]] = []

    if _HAS_SCIPY and all_patterns:
        try:
            ilp_result = _ilp_select(
                all_patterns, demand, bar_counts, distinct_lengths, bar_types)
            if ilp_result:
                selected = ilp_result
                for bar_len, pat in selected:
                    for l, cnt in pat.items():
                        remaining[l] -= cnt
                    bar_counts[bar_len] -= 1
        except Exception:
            selected = []
            remaining = dict(demand)
            bar_counts = {}
            for sv in vorrat:
                bar_counts[sv.laenge] = bar_counts.get(sv.laenge, 0) + sv.anzahl

    if not selected and all_patterns:
        all_patterns.sort(key=lambda x: x[2], reverse=True)
        for bar_len, pat, _score in all_patterns:
            if bar_counts.get(bar_len, 0) <= 0:
                continue
            if not any(remaining.get(l, 0) > 0 for l in pat):
                continue
            max_times = bar_counts[bar_len]
            for l, c in pat.items():
                if c > 0 and remaining.get(l, 0) >= 0:
                    max_times = min(max_times, remaining.get(l, 0) // c)
            if max_times <= 0:
                continue
            for _ in range(max_times):
                selected.append((bar_len, dict(pat)))
            for l, c in pat.items():
                remaining[l] -= c * max_times
            bar_counts[bar_len] -= max_times

    leftover_teile = []
    for l in distinct_lengths:
        r = remaining.get(l, 0)
        if r > 0:
            for lab in labels_by_len[l][-r:]:
                leftover_teile.append((lab, l, 1))

    if leftover_teile:
        leftover_vorrat = []
        for bl, svlist in bar_types.items():
            bc = bar_counts.get(bl, 0)
            if bc > 0:
                leftover_vorrat.append(StangenVorrat(
                    svlist[0].lagerstueck_id, bl, bc))
        if leftover_vorrat:
            fallback = _optimize_1d_bfd(leftover_teile, leftover_vorrat, kerf, None)
        else:
            fallback = OptimierungsErgebnis(
                fehlende_teile=[lab for lab, _, _ in leftover_teile])

    verfuegbar: list[dict] = []
    bar_idx = 0
    sv_usage: dict[float, int] = {}

    for bar_len, pat in selected:
        sv_idx = sv_usage.get(bar_len, 0)
        sv_usage[bar_len] = sv_idx + 1
        svlist = bar_types[bar_len]
        cum = 0
        sv = svlist[0]
        for s in svlist:
            cum += s.anzahl
            if sv_idx < cum:
                sv = s
                break

        platzierungen = []
        pos = 0.0
        for l in distinct_lengths:
            c = pat.get(l, 0)
            for _ in range(c):
                if not labels_by_len.get(l):
                    break
                if platzierungen:
                    pos += kerf
                lab = labels_by_len[l].pop(0)
                platzierungen.append(
                    Platzierung(teil_label=lab, laenge=l, x=pos))
                pos += l

        rest = bar_len - pos
        verfuegbar.append({
            "id": sv.lagerstueck_id,
            "stueck_nr": sv_idx + 1,
            "laenge": bar_len,
            "rest": rest,
            "platzierungen": platzierungen,
            "_offset": 0.0,
            "_bar": bar_idx,
        })
        bar_idx += 1

    result = _build_1d_result_segments(verfuegbar, [], kerf)

    if leftover_teile:
        result.schnittplaene.extend(fallback.schnittplaene)
        result.fehlende_teile.extend(fallback.fehlende_teile)
        gesamt_nutzbar = sum(s.lager_laenge for s in result.schnittplaene)
        gesamt_genutzt = sum(
            sum(p.laenge for p in s.platzierungen) for s in result.schnittplaene)
        if gesamt_nutzbar > 0:
            result.gesamt_verschnitt_prozent = round(
                (1 - gesamt_genutzt / gesamt_nutzbar) * 100, 1)

    return result


def _ilp_select(
    patterns: list[tuple[float, dict[float, int], float]],
    demand: dict[float, int],
    bar_supply: dict[float, int],
    distinct_lengths: list[float],
    bar_types: dict[float, list],
) -> list[tuple[float, dict[float, int]]]:
    """Select patterns via ILP (Integer Linear Programming) to minimize bars."""
    n = len(patterns)
    bar_len_keys = sorted(bar_types.keys())

    rows, lb, ub = [], [], []
    for l in distinct_lengths:
        rows.append([float(p.get(l, 0)) for _, p, _ in patterns])
        lb.append(float(demand[l]))
        ub.append(np.inf)
    for bl in bar_len_keys:
        rows.append([1.0 if pbl == bl else 0.0 for pbl, _, _ in patterns])
        lb.append(0.0)
        ub.append(float(bar_supply[bl]))

    res = milp(
        np.ones(n),
        constraints=LinearConstraint(np.array(rows, dtype=float), lb, ub),
        integrality=np.ones(n),
        bounds=Bounds(lb=0),
    )
    if not res.success:
        return []

    x = np.round(res.x).astype(int)
    selected = []
    for j in range(n):
        if x[j] > 0:
            bar_len, pat, _ = patterns[j]
            for _ in range(x[j]):
                selected.append((bar_len, dict(pat)))
    return selected


def _enumerate_patterns(
    bar_len: float,
    lengths: list[float],
    kerf: float,
    _max_patterns: int = 5000,
) -> list[dict[float, int]]:
    """Enumerate feasible cutting patterns for a bar via bounded DFS.

    Returns only maximal patterns (where no additional part fits).
    """
    patterns: list[dict[float, int]] = []

    def _dfs(idx: int, remaining: float, current: dict[float, int],
             n_parts: int) -> None:
        if len(patterns) >= _max_patterns:
            return
        is_maximal = True
        for i in range(idx, len(lengths)):
            l = lengths[i]
            needed = l + (kerf if n_parts > 0 else 0)
            if remaining >= needed:
                is_maximal = False
                max_count = int((remaining - l) // (l + kerf)) + 1 if l + kerf > 0 else 1
                for c in range(max_count, 0, -1):
                    total_needed = c * l + (c - 1) * kerf
                    if n_parts > 0:
                        total_needed += kerf
                    if remaining >= total_needed:
                        current[l] = current.get(l, 0) + c
                        _dfs(i + 1, remaining - total_needed, current,
                             n_parts + c)
                        current[l] -= c
                        if current[l] == 0:
                            del current[l]
                        if len(patterns) >= _max_patterns:
                            return
        if is_maximal and current:
            patterns.append(dict(current))

    _dfs(0, bar_len, {}, 0)
    return patterns


def _optimize_1d_bfd(
    teile: list[tuple[str, float, int]],
    vorrat: list[StangenVorrat],
    kerf: float = 3.0,
    defekte: dict[int, dict[int, list]] | None = None,
) -> OptimierungsErgebnis:
    """Best-Fit-Decreasing fallback for 1D (handles defects)."""
    einzelteile: list[tuple[str, float]] = []
    for label, laenge, anzahl in teile:
        einzelteile.extend((label, laenge) for _ in range(anzahl))
    einzelteile.sort(key=lambda t: t[1], reverse=True)

    verfuegbar: list[dict] = []
    bar_idx = 0
    for sv in sorted(vorrat, key=lambda s: s.laenge):
        defekte_map = defekte.get(sv.lagerstueck_id, {}) if defekte else {}
        for copy_idx in range(sv.anzahl):
            stueck_nr = copy_idx + 1
            defs = sorted(defekte_map.get(stueck_nr, []),
                           key=lambda d: d.position)
            if defs:
                segments = _split_bar_by_defects(sv.laenge, defs, kerf)
                for seg_start, seg_len in segments:
                    if seg_len > 0:
                        verfuegbar.append({
                            "id": sv.lagerstueck_id,
                            "stueck_nr": stueck_nr,
                            "laenge": seg_len,
                            "rest": seg_len,
                            "platzierungen": [],
                            "_offset": seg_start,
                            "_bar": bar_idx,
                            "_bar_len": sv.laenge,
                        })
            else:
                verfuegbar.append({
                    "id": sv.lagerstueck_id,
                    "stueck_nr": stueck_nr,
                    "laenge": sv.laenge,
                    "rest": sv.laenge,
                    "platzierungen": [],
                    "_offset": 0.0,
                    "_bar": bar_idx,
                })
            bar_idx += 1

    fehlend: list[str] = []

    for label, teil_laenge in einzelteile:
        best_stange = None
        best_rest = float('inf')
        for stange in verfuegbar:
            benoetigte_breite = teil_laenge
            if stange["platzierungen"]:
                benoetigte_breite += kerf
            if stange["rest"] >= benoetigte_breite:
                nach_rest = stange["rest"] - benoetigte_breite
                if nach_rest < best_rest:
                    best_rest = nach_rest
                    best_stange = stange
        if best_stange is not None:
            benoetigte_breite = teil_laenge
            if best_stange["platzierungen"]:
                benoetigte_breite += kerf
            pos = best_stange["laenge"] - best_stange["rest"]
            if best_stange["platzierungen"]:
                pos += kerf
            best_stange["platzierungen"].append(
                Platzierung(teil_label=label, laenge=teil_laenge,
                            x=pos + best_stange["_offset"])
            )
            best_stange["rest"] -= benoetigte_breite
        else:
            fehlend.append(label)

    return _build_1d_result_segments(verfuegbar, fehlend, kerf)


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
    defekte: dict[int, dict[int, list]] | None = None,
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
        defekte_map = defekte.get(pv.lagerstueck_id, {}) if defekte else {}
        for copy_idx in range(pv.anzahl):
            stueck_nr = copy_idx + 1
            freiraeume = [_Freiraum(0, 0, pv.laenge, pv.breite)]
            for d in defekte_map.get(stueck_nr, []):
                freiraeume = _subtract_rect(
                    freiraeume, d.position, d.position_y,
                    d.laenge, d.breite, kerf)
            platten.append({
                "id": pv.lagerstueck_id,
                "stueck_nr": stueck_nr,
                "laenge": pv.laenge,
                "breite": pv.breite,
                "freiraeume": freiraeume,
                "platzierungen": [],
            })

    fehlend: list[str] = []

    for label, t_laenge, t_breite in einzelteile:
        platziert = False
        best_platte = None
        best_freiraum_idx = None
        best_gedreht = False
        best_rest_flaeche = float("inf")

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
            stueck_nr=platte.get("stueck_nr", 0),
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
    defekte: dict[int, dict[int, list]] | None = None,
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
        return optimize_2d(teile, vorrat, kerf, drehung_erlaubt, teil_drehung,
                           defekte)

    def get_orient(label):
        if teil_drehung and label in teil_drehung:
            return teil_drehung[label]
        return True, drehung_erlaubt

    platten: list[dict] = []
    for pv in sorted(vorrat, key=lambda p: p.laenge * p.breite):
        defekte_map = defekte.get(pv.lagerstueck_id, {}) if defekte else {}
        for copy_idx in range(pv.anzahl):
            stueck_nr = copy_idx + 1
            freiraeume = [_Freiraum(0, 0, pv.laenge, pv.breite)]
            for d in defekte_map.get(stueck_nr, []):
                freiraeume = _subtract_rect(
                    freiraeume, d.position, d.position_y,
                    d.laenge, d.breite, kerf)
            platten.append({
                "id": pv.lagerstueck_id,
                "stueck_nr": stueck_nr,
                "laenge": pv.laenge, "breite": pv.breite,
                "freiraeume": freiraeume,
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
# Safety net: after this many seconds the search stops and returns the
# best plan found so far (never worse than the seeded start solution).
_GA_TIME_LIMIT = 10.0


def optimize_1d_ga(
    teile: list[tuple[str, float, int]],
    vorrat: list[StangenVorrat],
    kerf: float = 3.0,
    defekte: dict[int, dict[int, list]] | None = None,
) -> OptimierungsErgebnis:
    """1D cutting stock with a genetic algorithm.

    Chromosome = permutation of the part order; placement itself is
    deterministic first-fit per permutation, so the GA only searches
    the ordering. Fitness = total placed length. The FFD ordering is
    seeded into the initial population, so the GA can never end up
    worse than plain FFD.

    Note: random.Random(42) makes runs reproducible – two runs on the
    same input return the same plan, unless the search hits
    _GA_TIME_LIMIT (then a slower machine stops earlier).
    """
    einzelteile: list[tuple[str, float]] = []
    for label, laenge, anzahl in teile:
        einzelteile.extend((label, laenge) for _ in range(anzahl))

    # Fewer than two parts: nothing to reorder (crossover needs two)
    if len(einzelteile) < 2 or not vorrat:
        return optimize_1d(teile, vorrat, kerf, defekte)

    n = len(einzelteile)
    rng = random.Random(42)

    def _expand_bars():
        bars = []
        for sv in sorted(vorrat, key=lambda s: s.laenge):
            defekte_map = defekte.get(sv.lagerstueck_id, {}) if defekte else {}
            for copy_idx in range(sv.anzahl):
                defs = sorted(defekte_map.get(copy_idx + 1, []),
                               key=lambda d: d.position)
                if defs:
                    for _, seg_len in _split_bar_by_defects(sv.laenge, defs, kerf):
                        if seg_len > 0:
                            bars.append(seg_len)
                else:
                    bars.append(sv.laenge)
        return bars

    # Uncut bars of the same length are interchangeable – best-fit always
    # picks the first of them. evaluate() therefore only scans bars that
    # are already cut plus the first uncut bar per length. Same result as
    # scanning every bar, but the run time no longer grows with the stock.
    _gruppen: dict[float, list[int]] = {}
    for bar_i, bl in enumerate(_expand_bars()):
        _gruppen.setdefault(bl, []).append(bar_i)

    def evaluate(perm: list[int]) -> float:
        # Entries [index, rest, part count, length], sorted by index
        aktiv = sorted([idxs[0], bl, 0, bl] for bl, idxs in _gruppen.items())
        naechste = dict.fromkeys(_gruppen, 1)
        genutzt = 0.0
        for idx in perm:
            _, teil_laenge = einzelteile[idx]
            best_st = None
            best_rest = float('inf')
            for st in aktiv:
                bed = teil_laenge + (kerf if st[2] > 0 else 0)
                if st[1] >= bed:
                    nach_rest = st[1] - bed
                    if nach_rest < best_rest:
                        best_rest = nach_rest
                        best_st = st
            if best_st is not None:
                if best_st[2] == 0:
                    bl = best_st[3]
                    k = naechste[bl]
                    if k < len(_gruppen[bl]):
                        bisect.insort(aktiv, [_gruppen[bl][k], bl, 0, bl])
                        naechste[bl] = k + 1
                bed = teil_laenge + (kerf if best_st[2] > 0 else 0)
                best_st[1] -= bed
                best_st[2] += 1
                genutzt += teil_laenge
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
    deadline = time.monotonic() + _GA_TIME_LIMIT

    for _ in range(_GA_GENERATIONS):
        if time.monotonic() > deadline:
            break
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
    bar_idx = 0
    for sv in sorted(vorrat, key=lambda s: s.laenge):
        defekte_map = defekte.get(sv.lagerstueck_id, {}) if defekte else {}
        for copy_idx in range(sv.anzahl):
            stueck_nr = copy_idx + 1
            defs = sorted(defekte_map.get(stueck_nr, []),
                           key=lambda d: d.position)
            if defs:
                for seg_start, seg_len in _split_bar_by_defects(sv.laenge, defs, kerf):
                    if seg_len > 0:
                        verfuegbar.append({
                            "id": sv.lagerstueck_id, "stueck_nr": stueck_nr,
                            "laenge": seg_len,
                            "rest": seg_len, "platzierungen": [],
                            "_offset": seg_start, "_bar": bar_idx,
                            "_bar_len": sv.laenge,
                        })
            else:
                verfuegbar.append({
                    "id": sv.lagerstueck_id, "stueck_nr": stueck_nr,
                    "laenge": sv.laenge,
                    "rest": sv.laenge, "platzierungen": [],
                    "_offset": 0.0, "_bar": bar_idx,
                })
            bar_idx += 1

    fehlend: list[str] = []
    for idx in best:
        label, teil_laenge = einzelteile[idx]
        best_st = None
        best_rest = float('inf')
        for st in verfuegbar:
            bed = teil_laenge + (kerf if st["platzierungen"] else 0)
            if st["rest"] >= bed:
                nach_rest = st["rest"] - bed
                if nach_rest < best_rest:
                    best_rest = nach_rest
                    best_st = st
        if best_st is not None:
            bed = teil_laenge + (kerf if best_st["platzierungen"] else 0)
            pos = best_st["laenge"] - best_st["rest"]
            if best_st["platzierungen"]:
                pos += kerf
            best_st["platzierungen"].append(
                Platzierung(teil_label=label, laenge=teil_laenge,
                            x=pos + best_st["_offset"]))
            best_st["rest"] -= bed
        else:
            fehlend.append(label)

    return _build_1d_result_segments(verfuegbar, fehlend, kerf)


def optimize_2d_ga(
    teile: list[tuple[str, float, float, int]],
    vorrat: list[PlattenVorrat],
    kerf: float = 3.0,
    drehung_erlaubt: bool = True,
    teil_drehung: dict[str, tuple[bool, bool]] | None = None,
    defekte: dict[int, dict[int, list]] | None = None,
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

    if len(einzelteile) < 2 or not vorrat:
        return optimize_2d(teile, vorrat, kerf, drehung_erlaubt, teil_drehung,
                           defekte)

    n = len(einzelteile)
    rng = random.Random(42)

    def get_orient(label):
        if teil_drehung and label in teil_drehung:
            return teil_drehung[label]
        return True, drehung_erlaubt

    def _init_freiraeume(pv, stueck_nr):
        freiraeume = [_Freiraum(0, 0, pv.laenge, pv.breite)]
        defekte_map = defekte.get(pv.lagerstueck_id, {}) if defekte else {}
        for d in defekte_map.get(stueck_nr, []):
            freiraeume = _subtract_rect(
                freiraeume, d.position, d.position_y,
                d.laenge, d.breite, kerf)
        return freiraeume

    # Same idea as in 1D: unused panels of the same size without defects
    # are interchangeable, first-fit always lands in the first of them.
    # evaluate() only keeps used panels plus the first unused panel per
    # group (each panel with defects is its own group), in stock order.
    # Same result, run time independent of the stock size.
    _gruppen: dict[tuple, list[tuple[int, PlattenVorrat, int]]] = {}
    plate_i = 0
    for pv in sorted(vorrat, key=lambda p: p.laenge * p.breite):
        defekte_map = defekte.get(pv.lagerstueck_id, {}) if defekte else {}
        for copy_idx in range(pv.anzahl):
            stueck_nr = copy_idx + 1
            key = (("d", pv.lagerstueck_id, stueck_nr)
                   if defekte_map.get(stueck_nr) else (pv.laenge, pv.breite))
            _gruppen.setdefault(key, []).append((plate_i, pv, stueck_nr))
            plate_i += 1

    def _neue_platte(key, k):
        i, pv, stueck_nr = _gruppen[key][k]
        return [i, {"laenge": pv.laenge, "breite": pv.breite, "_key": key,
                    "freiraeume": _init_freiraeume(pv, stueck_nr)}]

    def evaluate(perm, rots):
        # Entries [index, panel], sorted by index
        aktiv = sorted((_neue_platte(key, 0) for key in _gruppen),
                       key=lambda e: e[0])
        naechste = dict.fromkeys(_gruppen, 1)
        placed = 0
        for pos, idx in enumerate(perm):
            label, tl, tb = einzelteile[idx]
            normal_ok, gedreht_ok = get_orient(label)
            if rots[pos] and gedreht_ok:
                tl, tb = tb, tl
            elif not normal_ok and gedreht_ok:
                tl, tb = tb, tl
            for _, plate in aktiv:
                best_fi, best_rest = None, float("inf")
                for fi, fr in enumerate(plate["freiraeume"]):
                    if tl <= fr.laenge and tb <= fr.breite:
                        r = fr.flaeche - tl * tb
                        if r < best_rest:
                            best_rest, best_fi = r, fi
                if best_fi is not None:
                    if not plate.get("_used"):
                        key = plate["_key"]
                        k = naechste[key]
                        if k < len(_gruppen[key]):
                            bisect.insort(aktiv, _neue_platte(key, k),
                                          key=lambda e: e[0])
                            naechste[key] = k + 1
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
                        for _, p in aktiv if p.get("_used"))
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
    deadline = time.monotonic() + _GA_TIME_LIMIT

    for _ in range(_GA_GENERATIONS):
        if time.monotonic() > deadline:
            break
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
        for copy_idx in range(pv.anzahl):
            stueck_nr = copy_idx + 1
            platten.append({
                "id": pv.lagerstueck_id,
                "stueck_nr": stueck_nr,
                "laenge": pv.laenge, "breite": pv.breite,
                "freiraeume": _init_freiraeume(pv, stueck_nr),
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
        teile, vorrat, kerf, drehung_erlaubt, teil_drehung, defekte)
    return min(
        (ga_result, nested_result),
        key=lambda r: (len(r.fehlende_teile), r.gesamt_verschnitt_prozent),
    )


# =====================================================================
# Shared result builders
# =====================================================================

def _subtract_rect(freiraeume: list[_Freiraum],
                   dx: float, dy: float, dl: float, db: float,
                   kerf: float) -> list[_Freiraum]:
    """Remove a rectangular defect area from a list of free rectangles.

    Each free rectangle that overlaps the defect is split into up to four
    non-overlapping sub-rectangles (left, right, top, bottom strips).
    """
    result: list[_Freiraum] = []
    for fr in freiraeume:
        fx2 = fr.x + fr.laenge
        fy2 = fr.y + fr.breite
        dx2 = dx + dl
        dy2 = dy + db

        if dx >= fx2 or dx2 <= fr.x or dy >= fy2 or dy2 <= fr.y:
            result.append(fr)
            continue

        # Left strip
        left_w = max(0, dx - fr.x - kerf)
        if left_w > 0:
            result.append(_Freiraum(fr.x, fr.y, left_w, fr.breite))
        # Right strip
        right_start = dx2 + kerf
        right_w = max(0, fx2 - right_start)
        if right_w > 0:
            result.append(_Freiraum(right_start, fr.y, right_w, fr.breite))
        # Top strip (between left and right)
        mid_x = max(fr.x, dx - kerf) if left_w <= 0 else dx - kerf
        mid_x = max(fr.x, dx)
        mid_x2 = min(fx2, dx2)
        mid_w = mid_x2 - mid_x
        top_h = max(0, dy - fr.y - kerf)
        if mid_w > 0 and top_h > 0:
            result.append(_Freiraum(mid_x, fr.y, mid_w, top_h))
        # Bottom strip (between left and right)
        bot_start = dy2 + kerf
        bot_h = max(0, fy2 - bot_start)
        if mid_w > 0 and bot_h > 0:
            result.append(_Freiraum(mid_x, bot_start, mid_w, bot_h))

    return result


def _split_bar_by_defects(bar_length: float, defects: list,
                          kerf: float) -> list[tuple[float, float]]:
    """Split a bar into usable segments around defect zones.

    Returns list of (start_offset, segment_length) pairs.
    """
    segments: list[tuple[float, float]] = []
    cursor = 0.0
    for d in sorted(defects, key=lambda d: d.position):
        seg_len = d.position - cursor
        if seg_len > kerf:
            segments.append((cursor, seg_len))
        cursor = d.position + d.laenge
    if bar_length - cursor > kerf:
        segments.append((cursor, bar_length - cursor))
    return segments


def _sort_1d_placements(platzierungen: list[Platzierung], kerf: float,
                        offset: float = 0.0) -> None:
    """Sort placements on a bar by length descending, recalculate positions."""
    platzierungen.sort(key=lambda p: p.laenge, reverse=True)
    pos = offset
    for i, p in enumerate(platzierungen):
        if i > 0:
            pos += kerf
        p.x = pos
        pos += p.laenge


def _build_1d_result_segments(verfuegbar, fehlend, kerf):
    """Build 1D result, merging segments of the same physical bar.

    A bar with defects consists of several segments (see
    _split_bar_by_defects). Parts are arranged within their own segment,
    so they never overlap a defect. lager_laenge is the physical bar
    length; each segment's unused end becomes a separate rest
    (laenge, x), because the defect zones in between are cut out as waste.
    """
    by_bar: dict[int, list] = {}
    for st in verfuegbar:
        by_bar.setdefault(st["_bar"], []).append(st)

    ergebnis = OptimierungsErgebnis(fehlende_teile=fehlend)
    gesamt_nutzbar = gesamt_genutzt = 0.0

    for _, segments in sorted(by_bar.items()):
        # Bars that stay uncut are not part of the plan
        if not any(seg["platzierungen"] for seg in segments):
            continue
        segments.sort(key=lambda seg: seg["_offset"])
        all_platz: list = []
        reste: list[tuple[float, float]] = []
        kv = 0.0
        lid = segments[0]["id"]
        stueck_nr = segments[0].get("stueck_nr", 0)
        bar_len = segments[0].get("_bar_len", segments[0]["laenge"])
        for seg in segments:
            platz = seg["platzierungen"]
            _sort_1d_placements(platz, kerf, seg["_offset"])
            all_platz.extend(platz)
            kv += kerf * max(0, len(platz) - 1)
            if seg["rest"] > 0:
                seg_end = seg["_offset"] + seg["laenge"]
                reste.append((seg["rest"], seg_end - seg["rest"]))

        genutzt = sum(p.laenge for p in all_platz)
        verschnitt = bar_len - genutzt - kv
        ergebnis.schnittplaene.append(Schnittplan(
            lagerstueck_id=lid, lager_laenge=bar_len,
            stueck_nr=stueck_nr, platzierungen=all_platz,
            reste=reste,
            verschnitt_mm=verschnitt,
            verschnitt_prozent=round(verschnitt / bar_len * 100, 1)
            if bar_len > 0 else 0))
        gesamt_nutzbar += bar_len
        gesamt_genutzt += genutzt

    if gesamt_nutzbar > 0:
        ergebnis.gesamt_verschnitt_prozent = round(
            (1 - gesamt_genutzt / gesamt_nutzbar) * 100, 1)
    return ergebnis


def _build_1d_result(verfuegbar, fehlend, kerf):
    ergebnis = OptimierungsErgebnis(fehlende_teile=fehlend)
    gesamt_nutzbar = gesamt_genutzt = 0.0
    for st in verfuegbar:
        if not st["platzierungen"]:
            continue
        _sort_1d_placements(st["platzierungen"], kerf)
        genutzt = sum(p.laenge for p in st["platzierungen"])
        kv = kerf * max(0, len(st["platzierungen"]) - 1)
        verschnitt = st["laenge"] - genutzt - kv
        ergebnis.schnittplaene.append(Schnittplan(
            lagerstueck_id=st["id"], lager_laenge=st["laenge"],
            stueck_nr=st.get("stueck_nr", 0),
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
            lager_breite=pl["breite"], stueck_nr=pl.get("stueck_nr", 0),
            platzierungen=pl["platzierungen"],
            reste=reste, verschnitt_mm=fl - gen,
            verschnitt_prozent=round((fl - gen) / fl * 100, 1) if fl > 0 else 0))
        gesamt_flaeche += fl
        gesamt_genutzt += gen
    if gesamt_flaeche > 0:
        ergebnis.gesamt_verschnitt_prozent = round(
            (1 - gesamt_genutzt / gesamt_flaeche) * 100, 1)
    return ergebnis
