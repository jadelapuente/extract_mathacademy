from __future__ import annotations

from typing import Any


def prepare_mochi_decks(
    raw_decks: list[dict[str, Any]] | dict[str, Any],
    *,
    root_deck_id: str | None = None,
    root_deck_name: str = "Math",
) -> list[dict[str, Any]]:
    decks = _deck_docs(raw_decks)
    deck_by_id = {deck["id"]: deck for deck in decks}
    root = _find_root_deck(decks, root_deck_id=root_deck_id, name=root_deck_name)
    children_by_parent = _children_by_parent(decks)
    root_id = root["id"]

    candidates: list[dict[str, Any]] = []
    stack: list[tuple[str, list[str]]] = [(root_id, [root["name"]])]
    visited: set[str] = set()
    while stack:
        deck_id, path_parts = stack.pop()
        if deck_id in visited:
            continue
        visited.add(deck_id)
        deck = deck_by_id[deck_id]
        path = " / ".join(path_parts)
        children = children_by_parent.get(deck_id, [])
        candidates.append(
            {
                "id": deck_id,
                "name": path,
            }
        )
        for child in reversed(children):
            stack.append((child["id"], path_parts + [child["name"]]))

    return candidates


def _deck_docs(raw_decks: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(raw_decks, dict):
        docs = raw_decks.get("docs", [])
    else:
        docs = raw_decks
    return sorted(
        [deck for deck in docs if not deck.get("archived?") and not deck.get("trashed?")],
        key=lambda deck: (deck.get("sort", 0), deck.get("name", ""), deck.get("id", "")),
    )


def _find_root_deck(
    decks: list[dict[str, Any]],
    *,
    root_deck_id: str | None,
    name: str,
) -> dict[str, Any]:
    if root_deck_id:
        for deck in decks:
            if deck["id"] == root_deck_id:
                return deck
        raise ValueError(f"could not find Mochi root deck id: {root_deck_id}")

    normalized_name = name.casefold()
    matches = [deck for deck in decks if deck.get("name", "").casefold() == normalized_name]
    if not matches:
        raise ValueError(f"could not find Mochi root deck named: {name}")
    top_level_matches = [
        deck
        for deck in matches
        if not (deck.get("parent-id") or deck.get("parent_id"))
    ]
    return (top_level_matches or matches)[0]


def _children_by_parent(decks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    children: dict[str, list[dict[str, Any]]] = {}
    deck_ids = {deck["id"] for deck in decks}
    for deck in decks:
        parent_id = deck.get("parent-id") or deck.get("parent_id")
        if parent_id in deck_ids:
            children.setdefault(parent_id, []).append(deck)
    for child_decks in children.values():
        child_decks.sort(
            key=lambda deck: (deck.get("sort", 0), deck.get("name", ""), deck["id"])
        )
    return children
