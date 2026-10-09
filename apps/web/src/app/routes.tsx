import { Navigate, Route, Routes } from "react-router";
import { Dashboard } from "../dashboard/Dashboard";
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
        {Object.keys(STUBS).map((path) => (
          <Route key={path} path={`${path}/*`} element={<Stub />} />
        ))}
        <Route path="*" element={<Stub />} />
      </Route>
    </Routes>
  );
}
