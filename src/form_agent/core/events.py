"""Optional observation callback. Domain code does not depend on files or logging."""

from collections.abc import Callable, Mapping

type EventSink = Callable[[str, Mapping[str, object]], None]


def discard_event(name: str, data: Mapping[str, object]) -> None:
    pass
