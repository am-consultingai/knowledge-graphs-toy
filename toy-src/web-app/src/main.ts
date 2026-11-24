import { hello } from "greet-lib";
import { render } from "./render";

export function run(): void {
  render(hello("World"));
}
