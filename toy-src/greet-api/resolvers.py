from events import emit


def resolve_greeting(name: str) -> str:
    return f"Hello, {name}!"


def resolve_farewell(name: str) -> str:
    return f"Goodbye, {name}!"


def register_user(name: str) -> None:
    emit("USER_GREETED")
