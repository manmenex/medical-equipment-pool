import { useEffect, useRef } from "react";

import { registerFormDirty } from "@/offline/appUpdate";

/** Mark the calling form dirty while `dirty` is true (blocks applying a PWA update, S6). */
export function useDirtyForm(dirty: boolean): void {
  const token = useRef(Symbol("form"));
  useEffect(() => registerFormDirty(token.current, dirty), [dirty]);
}
