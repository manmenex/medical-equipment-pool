import { QueryClient } from "@tanstack/react-query";

// Shared so logout can wipe cached server data (PR25E S1; design section 12).
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      // Transactional lists: short freshness window so returning to a page
      // paints cached data instantly and refetches in the background.
      staleTime: 15_000,
    },
  },
});

// Reference data changes rarely (admin edits invalidate these keys).
// None of these carry HN.
for (const key of ["wards", "categories", "users"]) {
  queryClient.setQueryDefaults([key], { staleTime: 5 * 60_000 });
}
