import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { listWards } from "@/services/masterData";

// Roadmap PR9B review round 2 (Finding 1): the ward list this action
// depends on can be loading or can fail to load, independent of the
// correction mutation itself. Centralizing the query + guarded "is it safe
// to open the dialog right now" decision here means every entry point
// (WardCorrectionAction) gets the same loading/error/retry behavior for
// free, instead of re-deriving it per screen. The ["wards"] query key is
// shared with any other caller (e.g. ReturnPage's own ward-name display) --
// React Query dedupes identical keys, so multiple mounted callers do not
// trigger duplicate network requests.
export function useWardCorrection() {
  const wardsQuery = useQuery({ queryKey: ["wards"], queryFn: listWards });
  const [dialogOpen, setDialogOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Guard kept even though the trigger button is only ever rendered
  // enabled once wards have loaded successfully -- defends against a
  // stale click queued just before a loading/error state transition.
  function openDialog() {
    if (!wardsQuery.data || wardsQuery.isError || wardsQuery.isLoading) {
      return;
    }
    setDialogOpen(true);
  }

  function closeDialog() {
    setDialogOpen(false);
  }

  return {
    wards: wardsQuery.data,
    wardsLoading: wardsQuery.isLoading,
    wardsError: wardsQuery.isError,
    refetchWards: wardsQuery.refetch,
    dialogOpen,
    openDialog,
    closeDialog,
    triggerRef,
  };
}
