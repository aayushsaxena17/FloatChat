import { describeError } from "../api/hooks";

/** Loading, empty and error states with the correlation id (PRD 13.2) for support. */
export function StatusMessage({
  loading,
  error,
  empty,
  children,
}: {
  loading?: boolean;
  error?: unknown;
  empty?: string | false;
  children?: React.ReactNode;
}) {
  if (loading) {
    return (
      <p className="status" role="status">
        Loading…
      </p>
    );
  }
  if (error) {
    const described = describeError(error);
    return (
      <p className="status" data-kind="error" role="alert">
        {described.message}
        {described.code ? ` [${described.code}]` : ""}
        {described.correlationId
          ? ` Correlation ID ${described.correlationId}.`
          : ""}
      </p>
    );
  }
  if (empty) {
    return (
      <p className="status" role="status">
        {empty}
      </p>
    );
  }
  return <>{children}</>;
}
