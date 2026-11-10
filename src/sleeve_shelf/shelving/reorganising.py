"""Application services for reorganising: carrying out a proposal on the shelves, a table full at a time.

Starting keeps the proposal as the target and records the sorting it was made by; the shelves
then change only with each step that is ticked off. The steps are worked out anew each time, from
the shelves as they stand (see sorting.reorganising), so moving an album by hand meanwhile, or
placing a new purchase, needs nothing of its own.
"""

from datetime import datetime

from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import (
    Album,
    Placement,
    PlacementSource,
    ProposedPlacement,
    Reorganisation,
    Shelf,
    TargetPlacement,
    WidthConstants,
)
from sleeve_shelf.library.taking_part import kept_shelf_ids, usable_shelves
from sleeve_shelf.library.versions import save_if_unsaved
from sleeve_shelf.persistence import BrowseQueries, JsonStore
from sleeve_shelf.shelving.places import shelf_options
from sleeve_shelf.shelving.proposal import adopt_sorting, has_proposal
from sleeve_shelf.sorting.reorganising import Situation, Step, StepKind, carry_out, plan, to_move


def running(store: JsonStore) -> Reorganisation | None:
    """The reorganisation that runs, if any.

    Args:
        store: The store of the collection.

    Returns:
        It, or None.
    """
    found = store.load(Reorganisation)
    return found[0] if found else None


def start(store: JsonStore, constants: WidthConstants) -> bool:
    """Start carrying out the waiting proposal: it becomes the target, the shelves stay as they are.

    The clusters and era bands it was sorted by are recorded, as accepting it does, and the layout
    as it is now is kept as a version. Albums already out of the cabinets for a reorganisation
    that ran stay on the table, or set aside, in the new one.

    Args:
        store: The store of the collection.
        constants: The width figures.

    Returns:
        False when there is no proposal to carry out.
    """
    if not has_proposal(store):
        return False
    proposed = store.load(ProposedPlacement)
    save_if_unsaved(store, "before reorganising")
    adopt_sorting(store)
    earlier = running(store)
    taking_part = _shelves(store)
    on_shelves = {p.album_id for p in store.load(Placement) if p.shelf_id in taking_part}
    target = [
        TargetPlacement(p.album_id, p.shelf_id, p.position, PlacementSource.ALGORITHM)
        for p in proposed
        if p.shelf_id in taking_part
    ]
    placed = {p.album_id for p in target}
    store.save(TargetPlacement, target)
    store.remove(ProposedPlacement)
    reorganisation = Reorganisation(
        started_at=datetime.now().replace(microsecond=0),
        table_records=load_settings(store.data_dir).table_records,
        to_move=0,
        on_table=list(earlier.on_table) if earlier else [],
        set_aside=list(earlier.set_aside) if earlier else [],
        left_out=sorted(on_shelves - placed),
    )
    reorganisation.to_move = len(to_move(_situation(store, reorganisation, constants)))
    store.save(Reorganisation, [reorganisation])
    return True


def stop(store: JsonStore) -> None:
    """End the reorganisation: what was done stands, the rest stays where it is.

    Albums on the table or set aside have no place from then on; they are listed among the albums
    without one.

    Args:
        store: The store of the collection.
    """
    store.remove(Reorganisation)
    store.remove(TargetPlacement)


def rounds(store: JsonStore, constants: WidthConstants) -> list[list[Step]]:
    """The rounds still to do, worked out from the shelves as they stand.

    Args:
        store: The store of the collection.
        constants: The width figures.

    Returns:
        The rounds; none when nothing runs or everything is done.
    """
    reorganisation = running(store)
    if reorganisation is None:
        return []
    return plan(_situation(store, reorganisation, constants))


def step_key(step: Step) -> str:
    """What names a step, so ticking it off is refused when the plan changed meanwhile.

    Args:
        step: The step.

    Returns:
        The key.
    """
    albums = ",".join(str(album) for album in step.album_ids)
    return f"{step.kind.value}:{step.shelf_id}:{step.after_album_id}:{albums}"


def tick_off(store: JsonStore, key: str, constants: WidthConstants) -> bool:
    """Do the first step of the plan, when it is still the one shown: the layout follows it.

    Args:
        store: The store of the collection.
        key: The step_key of the step that was shown.
        constants: The width figures.

    Returns:
        False when the plan changed meanwhile, or nothing runs; nothing is done then.
    """
    reorganisation = running(store)
    if reorganisation is None:
        return False
    situation = _situation(store, reorganisation, constants)
    remaining = plan(situation)
    if not remaining or step_key(remaining[0][0]) != key:
        return False
    step = remaining[0][0]
    placements = store.load(Placement)
    # Only the shelf the step is at changes; a step at no shelf changes none.
    rows = _rows(placements, {step.shelf_id} if step.shelf_id is not None else set())
    table, aside = list(situation.table), list(situation.aside)
    carry_out(rows, table, aside, step)
    store.save(Placement, _placed(placements, rows))
    reorganisation.on_table, reorganisation.set_aside = table, aside
    if step.kind in (StepKind.PUT, StepKind.LEAVE_OUT):
        reorganisation.moved += len(step.album_ids)
    if step.kind in (StepKind.TAKE, StepKind.TAKE_BACK):
        reorganisation.taken_in_round += len(step.album_ids)
    if len(remaining[0]) == 1:
        reorganisation.rounds_done += 1
        reorganisation.taken_in_round = 0
    store.save(Reorganisation, [reorganisation])
    return True


def _shelves(store: JsonStore) -> set[int]:
    """The shelves a reorganisation works on: those a proposal fills."""
    usable, _ = usable_shelves(store)
    kept = kept_shelf_ids(store)
    return {shelf.id for shelf in usable if shelf.id not in kept}


def _rows(placements: list[Placement], shelf_ids: set[int]) -> dict[int, list[int]]:
    rows: dict[int, list[int]] = {shelf: [] for shelf in shelf_ids}
    for p in sorted(placements, key=lambda p: (p.shelf_id, p.position)):
        if p.shelf_id in rows:
            rows[p.shelf_id].append(p.album_id)
    return rows


def _placed(placements: list[Placement], rows: dict[int, list[int]]) -> list[Placement]:
    """The placements with the shelves in rows as they now stand.

    An album taken off a shelf has none; one put on gets one from the reorganisation.
    """
    on = {album for row in rows.values() for album in row}
    kept = {p.album_id: p for p in placements}
    result = [p for p in placements if p.shelf_id not in rows and p.album_id not in on]
    for shelf, row in rows.items():
        for position, album in enumerate(row):
            source = kept[album].source if album in kept and kept[album].shelf_id == shelf else PlacementSource.ALGORITHM
            result.append(Placement(album, shelf, position, source))
    return result


def _situation(store: JsonStore, reorganisation: Reorganisation, constants: WidthConstants) -> Situation:
    """Where things are and where they go, from the store."""
    shelves = {shelf.id: shelf for shelf in store.load(Shelf)}
    taking_part = _shelves(store) & set(shelves)
    targets = [t for t in store.load(TargetPlacement) if t.shelf_id in taking_part]
    target_shelves = {t.shelf_id for t in targets}
    placements = store.load(Placement)
    placed = {p.album_id for p in placements}
    # An album put somewhere by hand meanwhile is no longer on the table, nor set aside.
    table = tuple(album for album in reorganisation.on_table if album not in placed)
    aside = tuple(album for album in reorganisation.set_aside if album not in placed)
    albums = {album.id: album for album in store.load(Album)}
    # An album removed meanwhile is gone from the target too.
    target = _rows([t for t in targets if t.album_id in albums], target_shelves)
    return Situation(
        rows=_rows(placements, taking_part | target_shelves),
        target=target,
        left_out=frozenset(album for album in reorganisation.left_out if album in albums),
        table=table,
        aside=aside,
        widths={i: album.width_cm or constants.base_per_disc for i, album in albums.items()},
        room={shelf: shelves[shelf].width_cm or 0.0 for shelf in taking_part},
        table_size=reorganisation.table_records,
        taken=reorganisation.taken_in_round,
    )


def reorganising_overview(store: JsonStore, constants: WidthConstants) -> dict:
    """What the Reorganise screen shows: progress, the round at hand, and what follows.

    Args:
        store: The store of the collection.
        constants: The width figures.

    Returns:
        What the screen's template uses, by name.
    """
    reorganisation = running(store)
    if reorganisation is None:
        return {"running": None, "has_proposal": has_proposal(store)}
    remaining = plan(_situation(store, reorganisation, constants))
    shown = remaining[0] if remaining else []
    album_ids = {album for step in shown for album in step.album_ids}
    album_ids |= {step.after_album_id for step in shown if step.after_album_id is not None}
    album_ids |= set(reorganisation.on_table)
    rows = BrowseQueries(store).albums(album_ids)
    shelf_names = _shelf_names(store)
    return {
        "running": reorganisation,
        "has_proposal": has_proposal(store),
        "round_number": reorganisation.rounds_done + 1,
        "rounds_left": len(remaining),
        "steps": [
            {
                "key": step_key(step),
                "kind": step.kind.value,
                "shelf": shelf_names.get(step.shelf_id),
                "shelf_id": step.shelf_id,
                "after": rows.get(step.after_album_id) if step.after_album_id is not None else None,
                "albums": [rows[album] for album in step.album_ids if album in rows],
            }
            for step in shown
        ],
        "on_table": len(reorganisation.on_table),
        "set_aside": len(reorganisation.set_aside),
        "done": not remaining,
    }


def _shelf_names(store: JsonStore) -> dict[int, str]:
    return {option["id"]: f"{option['cabinet']} › {option['shelf']}" for option in shelf_options(store)}
