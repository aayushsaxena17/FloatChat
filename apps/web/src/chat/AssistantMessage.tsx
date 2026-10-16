import { useMemo } from "react";
import { AlertCircle, RotateCcw } from "lucide-react";
import { usePlanQuery } from "../api/hooks";
import type { QueryPlan } from "../api/client";
import { tableRecords, type QueryResponse } from "../api/types";
import { axisTitle, columnLabel } from "../catalog/units";
import { ChartPanel } from "../charts/ChartPanel";
import { figuresFromChart } from "../charts/spec";
import { DataTable } from "../components/DataTable";
import { StatusMessage } from "../components/StatusMessage";
import { WaveMark } from "../components/WaveMark";
import { JobOffer, type JobOfferPayload } from "./JobOffer";
import { ProvenancePanel } from "../provenance/ProvenancePanel";
import {
  payloadOf,
  type ChatMessage,
  type Interpretation as InterpretationData,
} from "./client";
import { Interpretation } from "./Interpretation";

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
        <p className="chat-note" role="status">
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
        <details className="chat-table" open={figures.length === 0}>
          <summary>
            {response.result.row_count.toLocaleString("en-GB")} rows
            {response.result.row_count > 200 ? " (first 200 shown)" : ""}
          </summary>
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
        </details>
      ) : (
        <p className="chat-note" role="status">
          No rows matched.
        </p>
      )}
      <div className="chat-result-foot">
        <span>
          source {response.execution.source ?? "—"} ·{" "}
          {response.coverage.slots_covered}/{response.coverage.slots_total}{" "}
          coverage slots
        </span>
        <ProvenancePanel provenance={response.provenance} />
      </div>
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

/** One calm card for anything that went wrong: what happened and a retry. The error code and
 * the correlation id stay in the icon's tooltip for support, out of the reading flow. */
export function Problem({
  text,
  code,
  reference,
  onRetry,
}: {
  text: string;
  code: string;
  reference?: string | null;
  onRetry?: () => void;
}) {
  return (
    <div className="chat-problem" role="alert">
      <span
        className="chat-problem-icon"
        title={reference ? `${code} · ${reference}` : code}
      >
        <AlertCircle size={16} aria-hidden="true" />
      </span>
      <p className="chat-problem-text">{text}</p>
      {onRetry ? (
        <button type="button" className="chat-retry" onClick={onRetry}>
          <RotateCcw size={13} aria-hidden="true" />
          Try again
        </button>
      ) : null}
    </div>
  );
}

/** The assistant's mark beside each reply; its waves drift while a reply is being written. */
export function AssistantAvatar({ active = false }: { active?: boolean }) {
  return (
    <span className="chat-avatar" aria-hidden="true">
      <WaveMark size={16} active={active} />
    </span>
  );
}

export function AssistantMessage({
  message,
  onHint,
  onRetry,
}: {
  message: ChatMessage;
  onHint?: (hint: string) => void;
  onRetry?: () => void;
}) {
  const payload = payloadOf(message);
  const interpretation: InterpretationData | undefined = payload.interpretation;
  const missing =
    payload.clarification?.missing ??
    interpretation?.clarification?.missing ??
    [];
  const isError = message.kind === "error";
  // Greetings and conversational replies ran no query: nothing to interpret.
  const conversational = message.kind === "greeting" || message.kind === "help";
  return (
    <article
      className={`chat-message chat-assistant chat-kind-${message.kind}`}
      data-kind={message.kind}
    >
      <AssistantAvatar />
      <div className="chat-body">
        {isError ? (
          <Problem
            text={message.text}
            code={payload.code ?? "error"}
            reference={message.correlation_id}
            onRetry={onRetry}
          />
        ) : (
          <p className="chat-text">{message.text}</p>
        )}
        {message.kind === "clarification" && missing.length && onHint ? (
          <div
            className="chat-chips"
            role="group"
            aria-label="Suggested details"
          >
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
        {payload.job_offer ? (
          <JobOffer offer={payload.job_offer as JobOfferPayload} />
        ) : null}
        {payload.result ? <ResultView response={payload.result} /> : null}
        {!payload.result && payload.result_omitted && payload.plan ? (
          <StoredResult plan={payload.plan} />
        ) : null}
        {interpretation &&
        interpretation.kind &&
        !isError &&
        !conversational ? (
          <Interpretation data={interpretation} />
        ) : null}
      </div>
    </article>
  );
}
