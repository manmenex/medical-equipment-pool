import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { listRefs } from "@/offline/offlineStore";
import { listDepartments, listWards } from "@/services/masterData";
import type { Department, Ward } from "@/types";

/** Wards + departments (with phones): API online, IndexedDB snapshot offline. */
export function useWardRefs(offline: boolean): { wards: Ward[]; departments: Department[] } {
  const { data: onlineWards } = useQuery({ queryKey: ["wards"], queryFn: listWards });
  const { data: onlineDepartments } = useQuery({ queryKey: ["departments"], queryFn: listDepartments });
  const [cached, setCached] = useState<{ wards: Ward[]; departments: Department[] } | null>(null);
  useEffect(() => {
    if (!offline) return;
    let live = true;
    void Promise.all([listRefs("ref_wards"), listRefs("ref_departments")])
      .then(([w, d]) => live && setCached({ wards: w as unknown as Ward[], departments: d as unknown as Department[] }))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [offline]);
  return {
    wards: (offline && cached ? cached.wards : onlineWards) ?? [],
    departments: (offline && cached ? cached.departments : onlineDepartments) ?? [],
  };
}
