import { onEvent } from "./webhooks";

function sendDailyDigest(): void {
  console.log("Your daily digest");
}

onEvent("DAILY_DIGEST", sendDailyDigest);
