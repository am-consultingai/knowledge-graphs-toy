import { sendWelcomeMail } from "./mail";

type Handler = () => void;
const handlers: Record<string, Handler> = {};

export function onEvent(event: string, handler: Handler): void {
  handlers[event] = handler;
}

onEvent("USER_GREETED", sendWelcomeMail);
