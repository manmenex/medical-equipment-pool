import { QueryClient } from "@tanstack/react-query";

// Shared so logout can wipe cached server data (PR25E S1; design section 12).
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
