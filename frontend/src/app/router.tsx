import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "@/app/layout/AppShell";
import { StatusPage } from "@/app/StatusPage";

// Routes follow docs/architecture.md §4.2. Feature pages replace the placeholders as modules land;
// role guards are added with the identity feature.
export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <Navigate to="/status" replace /> },
      { path: "/status", element: <StatusPage /> },
      // { path: "/overview", element: <OverviewPage /> },          UI-01
      // { path: "/me", element: <StudentHomePage /> },             UI-02
      // { path: "/projects/:id", element: <ProjectPage /> },       UI-03
      // { path: "/students/:id", element: <StudentProfilePage /> },UI-04
      // { path: "/review/:assessmentId", element: <ReviewPage /> },UI-05
      // { path: "/exports", element: <ExportsPage /> },            UI-06
      // { path: "/notifications", element: <NotificationsPage /> },UI-07
      // { path: "/report/:periodId", element: <ReportEditorPage /> },
      // { path: "/assistant", element: <AssistantPage /> },
      { path: "*", element: <Navigate to="/status" replace /> },
    ],
  },
]);
