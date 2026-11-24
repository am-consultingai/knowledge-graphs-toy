import { goodbye } from "greet-lib";

export function hello(): string {
  return "hi";
}

export function leave(): string {
  return goodbye("World");
}
