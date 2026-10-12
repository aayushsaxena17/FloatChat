import { useMemo } from "react";
import { usePlanQuery } from "../api/hooks";
import type { QueryPlan } from "../api/client";
import { tableRecords, type QueryResponse } from "../api/types";
import { axisTitle, columnLabel } from "../catalog/units";
import { ChartPanel } from "../charts/ChartPanel";
import { figuresFromChart } from "../charts/spec";
import { DataTable } from "../components/DataTable";
import { StatusMessage } from "../components/StatusMessage";
import { ProvenancePanel } from "../provenance/ProvenancePanel";
import {
  payloadOf,
  type ChatMessage,
  type Interpretation as InterpretationData,
} from "./client";
import { Interpretation } from "./Interpretation";

const KIND_LABEL: Record<string, string> = {
  answer: "Answer",
  clarification: "Needs one more detail",
  greeting: "Hello",
  help: "What I can do",
  unsupported: "Not available",
  error: "Something went wrong",
};

const HINTS: Record<string, string> = {
  time_range: "in January 2025",
  geography: "in the Arabian Sea",
  depth_dbar: "in the upper 100 dbar",
  variables: "temperature",
  qc_policy: "with science-ready QC",
  operation: "monthly mean",
  presentation: "as a table",
};

function ResultView({ response }: { response: QueryResponse }) {
  const figures = useMemo(
    () =>
      response.chart ? figuresFromChart(response.chart, response.result) : [],
    [response],
  );
  const columns = response.result.columns.map((column) =>
    column.unit
      ? axisTitle(columnLabel(column.name), column.unit)
      : columnLabel(column.name),
  );
  const records = tableRecords(response.result);
  return (
    <div className="chat-result" data-testid="chat-result">
      {response.partial ? (
        <p className="status" data-kind="warning" role="status">
          Partial result: {response.missing.length} coverage slots are missing.
        </p>
      ) : null}
      {figures.map((figure) => (
        <ChartPanel
          key={figure.key}
          figure={figure}
          compact
          caption={response.interpretation.transformation as string | undefined}
        />
      ))}
      {records.length ? (
        <DataTable
          columns={columns}
          rows={
            response.result.rows as Array<
              Array<string | number | boolean | null>
            >
          }
          caption="Result rows"
          limit={200}
        />
      ) : (
        <p className="status" role="status">
          No rows matched.
        </p>
      )}
      <p className="chat-result-meta">
        {response.result.row_count.toLocaleString("en-GB")} rows · source{" "}
        {response.execution.source ?? "—"} · {response.coverage.slots_covered}/
        {response.coverage.slots_total} coverage slots
      </p>
      <ProvenancePanel provenance={response.provenance} />
    </div>
  );
}

/** Re-runs a stored plan when the result was too large to keep with the message. */
function StoredResult({ plan }: { plan: Record<string, unknown> }) {
  const query = usePlanQuery(plan as QueryPlan);
  return (
    <StatusMessage loading={query.isPending} error={query.error}>
      {query.data ? <ResultView response={query.data} /> : null}
    </StatusMessage>
  );
}

export function AssistantMessage({
  message,
  onHint,
}: {
  message: ChatMessage;
  onHint?: (hint: string) => void;
}) {
  const payload = payloadOf(message);
  const interpretation: InterpretationData | undefined = payload.interpretation;
  const missing =
    payload.clarification?.missing ??
    interpretation?.clarification?.missing ??
    [];
  return (
    <article
      className={`chat-message chat-assistant chat-kind-${message.kind}`}
      data-kind={message.kind}
    >
      <header>
        <span className="chat-role">FloatChat</span>
        <span className="chat-kind">
          {KIND_LABEL[message.kind] ?? message.kind}
        </span>
      </header>
      <p className="chat-text">{message.text}</p>
      {message.kind === "clarification" && missing.length && onHint ? (
        <div className="chat-chips" role="group" aria-label="Suggested details">
          {missing.map((field) => (
            <button
              key={field}
              type="button"
              className="chat-chip"
              onClick={() => onHint(HINTS[field] ?? field)}
            >
              {HINTS[field] ?? field}
            </button>
          ))}
        </div>
      ) : null}
      {message.kind === "error" && payload.code ? (
        <p className="status" data-kind="error" role="alert">
          [{payload.code}]
          {message.correlation_id
            ? ` Correlation ID ${message.correlation_id}.`
            : ""}
        </p>
      ) : null}
      {payload.result ? <ResultView response={payload.result} /> : null}
      {!payload.result && payload.result_omitted && payload.plan ? (
        <StoredResult plan={payload.plan} />
      ) : null}
      {interpretation && interpretation.kind ? (
        <Interpretation data={interpretation} />
      ) : null}
    </article>
  );
}
