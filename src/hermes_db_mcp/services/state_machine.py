TOPIC_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["writing", "archived"],
    "writing": ["published", "archived"],
    "published": ["archived"],
    "archived": [],
}

INSPIRATION_TRANSITIONS: dict[str, list[str]] = {
    "candidate": ["adopted", "archived"],
    "adopted": ["used", "archived"],
    "used": ["archived"],
    "archived": [],
}

_MACHINES = {
    "topic": TOPIC_TRANSITIONS,
    "inspiration": INSPIRATION_TRANSITIONS,
}


def validate_transition(entity_type: str, current: str, target: str) -> dict | None:
    transitions = _MACHINES.get(entity_type, {})
    allowed = transitions.get(current, [])
    if target in allowed:
        return None
    return {
        "error": "invalid_transition",
        "from": current,
        "to": target,
        "allowed": allowed,
    }
