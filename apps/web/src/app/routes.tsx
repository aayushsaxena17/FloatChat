import { Navigate, Route, Routes } from "react-router";
import { ChatPage } from "../chat/ChatPage";
import { Dashboard } from "../dashboard/Dashboard";
import { ForecastDetailPage } from "../forecasts/ForecastDetailPage";
import { ForecastsPage } from "../forecasts/ForecastsPage";
import { JobDetailPage } from "../jobs/JobDetailPage";
import { JobsPage } from "../jobs/JobsPage";
import { MapPage } from "../explorer/MapPage";
import { ProfilesView } from "../explorer/ProfilesView";
import { Layout } from "./Layout";
import { Stub, STUBS } from "./Stub";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/explore/map" element={<MapPage />} />
        <Route path="/explore/profiles" element={<ProfilesView />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
        <Route path="/forecasts" element={<ForecastsPage />} />
        <Route path="/forecasts/:forecastId" element={<ForecastDetailPage />} />
        {Object.keys(STUBS).map((path) => (
          <Route key={path} path={`${path}/*`} element={<Stub />} />
        ))}
        <Route path="*" element={<Stub />} />
      </Route>
    </Routes>
  );
}
