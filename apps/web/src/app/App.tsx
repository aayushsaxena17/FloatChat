import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { useState, type ReactNode } from "react";
import { BrowserRouter } from "react-router";
import { retryPolicy } from "../api/hooks";
import { DatasetGuard } from "./DatasetGuard";
import { ErrorBoundary } from "./ErrorBoundary";
import {
  PERSIST_BUSTER,
  PERSIST_MAX_AGE_MS,
  createPersister,
  persistenceAvailable,
  shouldPersistQuery,
} from "./persistence";
import { AppRoutes } from "./routes";

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: retryPolicy,
        staleTime: 60_000,
        // Persisted answers must stay in memory at least as long as they live on disk.
        gcTime: PERSIST_MAX_AGE_MS,
        refetchOnWindowFocus: false,
      },
    },
  });
}

function Providers({
  client,
  persist,
  children,
}: {
  client: QueryClient;
  persist: boolean;
  children: ReactNode;
}) {
  const [persister] = useState(() => (persist ? createPersister() : null));
  if (persister === null)
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  return (
    <PersistQueryClientProvider
      client={client}
      persistOptions={{
        persister,
        maxAge: PERSIST_MAX_AGE_MS,
        buster: PERSIST_BUSTER,
        dehydrateOptions: { shouldDehydrateQuery: shouldPersistQuery },
      }}
    >
      {children}
    </PersistQueryClientProvider>
  );
}

export function App({
  client,
  persist,
}: {
  client?: QueryClient;
  persist?: boolean;
}) {
  const [queryClient] = useState(() => client ?? createQueryClient());
  return (
    <Providers
      client={queryClient}
      persist={persist ?? (client === undefined && persistenceAvailable())}
    >
      <DatasetGuard />
      <BrowserRouter>
        <ErrorBoundary>
          <AppRoutes />
        </ErrorBoundary>
      </BrowserRouter>
    </Providers>
  );
}
