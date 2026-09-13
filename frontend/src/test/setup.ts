import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

// @testing-library/react's automatic-cleanup registration only fires when
// it detects a global `afterEach` (e.g. Jest, or Vitest with `globals:
// true`). This project intentionally keeps `globals: false` (explicit
// imports everywhere else in this codebase) -- cleanup is registered
// explicitly here instead, so a leftover DOM tree from one test can never
// leak into the next (e.g. a duplicate "same text" match).
afterEach(() => {
  cleanup();
});
