import { goodbye } from "greet-lib";

export function logout(user: string): string {
  return goodbye(user);
}
