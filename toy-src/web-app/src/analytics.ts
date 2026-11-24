type Handler = () => void;
const handlers: Record<string, Handler> = {};

export function onEvent(event: string, handler: Handler): void {
  handlers[event] = handler;
}

function trackPageView(): void {
  console.log("page viewed");
}

onEvent("PAGE_VIEWED", trackPageView);
