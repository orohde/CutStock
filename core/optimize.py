"""Optimierungsalgorithmen für Verschnittminimierung.

Keine GUI-Abhängigkeit – arbeitet nur mit den Dataclasses aus models.py.

Algorithmen:
  Greedy (schnell):
    1D: First-Fit-Decreasing
    2D: Best-Area-Fit Guillotine-Packing
  GA (gründlich):
    1D + 2D: Genetischer Algorithmus – testet viele Permutationen,
    selektiert die besten, kreuzt und mutiert. ~95%+ Materialausnutzung.

Beide berücksichtigen Schnittbreite (Kerf) und Maserungsrichtung.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


# =====================================================================
# Ergebnis-Datenklassen
# =====================================================================

@dataclass
class Platzierung:
    """Ein platziertes Teil auf einem Lagerstück."""
    teil_label: str
    laenge: float
    breite: float = 0.0  # nur Platte
    x: float = 0.0       # Position auf dem Lagerstück (nur Platte)
    y: float = 0.0
    gedreht: bool = False


@dataclass
class Schnittplan:
    """Plan für ein einzelnes Lagerstück."""
    lagerstueck_id: int
    lager_laenge: float
    lager_breite: float = 0.0
    platzierungen: list[Platzierung] = field(default_factory=list)
    reste: list[tuple[float, float]] = field(default_factory=list)  # (L, B) oder (L,)
    verschnitt_mm: float = 0.0
    verschnitt_prozent: float = 0.0


@dataclass
class OptimierungsErgebnis:
    """Gesamtergebnis eines Optimierungslaufs."""
    schnittplaene: list[Schnittplan] = field(default_factory=list)
    fehlende_teile: list[str] = field(default_factory=list)
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
    """1D Bin-Packing mit First-Fit-Decreasing.

    Args:
        teile: Liste von (label, länge, stückzahl) – wird zu Einzelstücken expandiert.
        vorrat: Verfügbare Stangen, sortiert nach Länge aufsteigend (kleine zuerst).
        kerf: Schnittbreite in mm.

    Strategie: Kleine/Rest-Stangen zuerst verbrauchen (sortiert aufsteigend),
    Teile absteigend nach Länge platzieren (FFD).
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
                "rest": sv.laenge,
                "platzierungen": [],
            })

    fehlend: list[str] = []

    for label, teil_laenge in einzelteile:
        platziert = False
        for stange in verfuegbar:
            benoetigte_breite = teil_laenge
            if stange["platzierungen"]:
                benoetigte_breite += kerf
            if stange["rest"] >= benoetigte_breite:
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
    """Ein freier rechteckiger Bereich auf einer Platte."""
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
    """2D Guillotine-Packing mit Best-Area-Fit.

    Args:
        teile: Liste von (label, länge, breite, stückzahl).
        vorrat: Verfügbare Platten.
        kerf: Schnittbreite in mm.
        drehung_erlaubt: Globaler Fallback – wird durch teil_drehung überschrieben.
        teil_drehung: Dict label → (normal_ok, gedreht_ok) pro Teil.
            Wenn angegeben, bestimmt dies die erlaubten Orientierungen.

    Guillotine-Constraint: Jeder Schnitt geht komplett durch den aktuellen
    Bereich – dadurch bleiben alle Reste Rechtecke.
    """
    einzelteile: list[tuple[str, float, float]] = []
    for label, laenge, breite, anzahl in teile:
        einzelteile.extend((label, laenge, breite) for _ in range(anzahl))
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

        # Erlaubte Orientierungen für dieses Teil bestimmen
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

            # Guillotine-Split: horizontaler Schnitt zuerst
            # Rechts neben dem Teil (gleiche Höhe wie Teil)
            rest_rechts_l = fr.laenge - tl - kerf
            if rest_rechts_l > 0:
                best_platte["freiraeume"].append(_Freiraum(
                    x=fr.x + tl + kerf, y=fr.y,
                    laenge=rest_rechts_l, breite=tb,
                ))

            # Oben über dem Teil (volle Breite des Freiraums)
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
# Nested Guillotine – verschachtelte Durchschnitte (2D)
# =====================================================================

def optimize_2d_nested(
    teile: list[tuple[str, float, float, int]],
    vorrat: list[PlattenVorrat],
    kerf: float = 3.0,
    drehung_erlaubt: bool = True,
    teil_drehung: dict[str, tuple[bool, bool]] | None = None,
) -> OptimierungsErgebnis:
    """2D Nested-Guillotine: testet beide Split-Richtungen pro Schnitt.

    Im Gegensatz zum einfachen Guillotine (immer horizontal-zuerst)
    testet dieser Algorithmus an jeder Schnittstelle ob ein horizontaler
    oder vertikaler Durchschnitt den grösseren zusammenhaengenden Rest
    erzeugt. Der grössere Rest kann besser fuer nachfolgende Teile
    genutzt werden.
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
                        # Berechne den groessten zusammenhaengenden Rest
                        if split == "h":
                            r1 = max(0, fr.laenge - tl - kerf) * tb
                            r2 = fr.laenge * max(0, fr.breite - tb - kerf)
                        else:
                            r1 = tl * max(0, fr.breite - tb - kerf)
                            r2 = max(0, fr.laenge - tl - kerf) * fr.breite
                        max_rest = max(r1, r2)

                        # Bevorzuge: 1) kleinstes Rest-Abfall
                        # 2) bei gleichem Rest: groesster zusammenhaengender Block
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

    return _build_2d_result(platten, fehlend)


# =====================================================================
# Genetischer Algorithmus (GA) – gründliche Optimierung
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
    """1D Cutting-Stock mit Genetischem Algorithmus.

    Chromosom = Permutation der Teile-Reihenfolge.
    Platzierung deterministisch mit FFD pro Permutation.
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

    ffd_order = sorted(range(n), key=lambda i: einzelteile[i][1], reverse=True)
    population = [ffd_order]
    for _ in range(_GA_POPULATION - 1):
        p = list(range(n))
        rng.shuffle(p)
        population.append(p)

    elite_count = max(2, int(_GA_POPULATION * _GA_ELITE_RATIO))

    for _ in range(_GA_GENERATIONS):
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
    """2D Guillotine-Packing mit Genetischem Algorithmus.

    Chromosom = Permutation + Drehungsentscheidungen.
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
        # Primär möglichst viele Teile platzieren, sekundär möglichst wenig
        # Brettfläche verbrauchen (weniger Bretter/Verschnitt, begünstigt Drehung).
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

    ga_result = _build_2d_result(platten, fehlend)

    # "Gründlich" soll nie schlechter sein als Nested Guillotine – beide
    # rechnen und das bessere (weniger fehlende Teile, dann weniger Verschnitt)
    # zurückgeben.
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


def _build_2d_result(platten, fehlend):
    ergebnis = OptimierungsErgebnis(fehlende_teile=fehlend)
    gesamt_flaeche = gesamt_genutzt = 0.0
    for pl in platten:
        if not pl["platzierungen"]:
            continue
        fl = pl["laenge"] * pl["breite"]
        gen = sum(p.laenge * p.breite for p in pl["platzierungen"])
        reste = [(fr.laenge, fr.breite) for fr in pl["freiraeume"]
                 if fr.laenge > 0 and fr.breite > 0]
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
