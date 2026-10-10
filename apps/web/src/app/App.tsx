import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter } from "react-router";
import { retryPolicy } from "../api/hooks";
import { ErrorBoundary } from "./ErrorBoundary";
import { AppRoutes } from "./routes";

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: retryPolicy,
        staleTime: 60_000,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export function App({ client }: { client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? createQueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ErrorBoundary>
          <AppRoutes />
        </ErrorBoundary>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
