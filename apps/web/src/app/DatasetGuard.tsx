import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useEnvironment } from "../api/hooks";
import { datasetVersion, guardDatasetVersion } from "./persistence";

/** Clears persisted answers when the server reports a different dataset version (ADR-0068). */
export function DatasetGuard() {
  const client = useQueryClient();
  const environment = useEnvironment();
  const version = datasetVersion(environment.data);
  useEffect(() => {
    guardDatasetVersion(client, version);
  }, [client, version]);
  return null;
}
