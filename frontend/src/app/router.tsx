import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "@/app/layout/AppShell";
import { RequireAuth } from "@/app/RequireAuth";
import { StatusPage } from "@/app/StatusPage";
import { LoginPage } from "@/features/auth/pages/LoginPage";
import { StudentHomePage } from "@/features/me/pages/StudentHomePage";
import { ReportEditorPage } from "@/features/report/pages/ReportEditorPage";

// Routes follow docs/architecture.md §4.2. Feature pages replace the placeholders as modules land.
export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <Navigate to="/me" replace /> },
      { path: "/login", element: <LoginPage /> },
      { path: "/status", element: <StatusPage /> },
      {
        element: <RequireAuth />,
        children: [
          { path: "/me", element: <StudentHomePage /> }, // UI-02
          { path: "/report/:periodId", element: <ReportEditorPage /> }, // REP-02, REP-03
        ],
      },
      // { path: "/overview", element: <OverviewPage /> },          UI-01
      // { path: "/projects/:id", element: <ProjectPage /> },       UI-03
      // { path: "/students/:id", element: <StudentProfilePage /> },UI-04
      // { path: "/review/:assessmentId", element: <ReviewPage /> },UI-05
      // { path: "/exports", element: <ExportsPage /> },            UI-06
      // { path: "/notifications", element: <NotificationsPage /> },UI-07
      // { path: "/assistant", element: <AssistantPage /> },
      { path: "*", element: <Navigate to="/me" replace /> },
    ],
  },
]);
