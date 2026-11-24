import hooks

HANDLERS = {"USER_GREETED": "on_user_greeted"}


def emit(event: str) -> None:
    handler = getattr(hooks, HANDLERS[event])
    handler()
