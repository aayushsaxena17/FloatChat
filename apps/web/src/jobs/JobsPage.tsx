import { Link } from "react-router";
import { ArrowUpRight, Download } from "lucide-react";
import { formatUtc } from "../catalog/units";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { StatusMessage } from "../components/StatusMessage";
import { progressLine, stateKind, stateLabel, titleOf } from "./format";
import { useJobs } from "./useJobs";

/** PRD 2.3: the job and export centre. Jobs belong to this browser until Stage 7 adds users. */
export function JobsPage() {
  const jobs = useJobs();
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Jobs</h1>
          <p className="page-description">
            Exports of many years run in the background: missing months are
            fetched from Argovis once, then the file is written and kept for
            seven days.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link to="/dashboard#observations">
            <Download aria-hidden="true" />
            New export from the dashboard
            <ArrowUpRight aria-hidden="true" />
          </Link>
        </Button>
      </div>
      <StatusMessage
        loading={jobs.isPending}
        error={jobs.error}
        empty={
          jobs.data && jobs.data.length === 0
            ? "No jobs yet. Choose a region and period on the dashboard and use Export filtered dataset."
            : false
        }
      >
        <ul className="job-list" aria-label="Jobs">
          {(jobs.data ?? []).map((job) => (
            <li key={job.id} className="job-row">
              <div className="job-row-main">
                <Link to={`/jobs/${job.id}`} className="job-title">
                  {titleOf(job)}
                </Link>
                <p className="job-meta">
                  Created {formatUtc(job.created_at)}
                  {progressLine(job) ? ` · ${progressLine(job)}` : ""}
                </p>
              </div>
              <Badge
                variant="outline"
                className="badge"
                data-kind={stateKind(job.state)}
              >
                {stateLabel(job.state)}
              </Badge>
            </li>
          ))}
        </ul>
      </StatusMessage>
    </>
  );
}
