def send_webhook(event: str) -> None:
    print(f"POST /webhooks {event}")


def on_user_greeted() -> None:
    send_webhook("USER_GREETED")
