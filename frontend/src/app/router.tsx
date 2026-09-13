import { createBrowserRouter } from "react-router-dom";

import { HomeRedirect } from "@/app/HomeRedirect";
import { AppShell } from "@/app/layout/AppShell";
import { RequireAuth } from "@/app/RequireAuth";
import { StatusPage } from "@/app/StatusPage";
import { AssistantPage } from "@/features/assistant/pages/AssistantPage";
import { LoginPage } from "@/features/auth/pages/LoginPage";
import { ExportsPage } from "@/features/exports/pages/ExportsPage";
import { StudentHomePage } from "@/features/me/pages/StudentHomePage";
import { NotificationsPage } from "@/features/notifications/pages/NotificationsPage";
import { OverviewPage } from "@/features/overview/pages/OverviewPage";
import { ProjectPage } from "@/features/projects/pages/ProjectPage";
import { ReportEditorPage } from "@/features/report/pages/ReportEditorPage";
import { ReviewPage } from "@/features/review/pages/ReviewPage";
import { StudentProfilePage } from "@/features/students/pages/StudentProfilePage";

// Routes follow docs/architecture.md §4.2. The role guard keeps the UI from offering a page the
// caller cannot load; the API enforces every permission itself (AUTH-02).
export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "/status", element: <StatusPage /> },
      {
        element: <RequireAuth />,
        children: [
          // "/" and anything unrecognised go to the home for this role, not to a fixed page.
          { path: "/", element: <HomeRedirect /> },
          { path: "*", element: <HomeRedirect /> },
          { path: "/projects/:id", element: <ProjectPage /> }, // UI-03
          { path: "/notifications", element: <NotificationsPage /> }, // UI-07
          { path: "/exports", element: <ExportsPage /> }, // UI-06
        ],
      },
      {
        // The student screens, guarded the way the professor's are. The weekly flow is a student
        // flow: the API answers a professor writing to a draft with 422, so offering it is
        // offering a dead end.
        element: <RequireAuth role="student" />,
        children: [
          { path: "/me", element: <StudentHomePage /> }, // UI-02
          { path: "/report/:periodId", element: <ReportEditorPage /> }, // REP-02, REP-03
        ],
      },
      {
        element: <RequireAuth role="prof" />,
        children: [
          { path: "/overview", element: <OverviewPage /> }, // UI-01
          { path: "/students/:id", element: <StudentProfilePage /> }, // UI-04
          { path: "/review/:assessmentId", element: <ReviewPage /> }, // UI-05
          { path: "/assistant", element: <AssistantPage /> }, // QA-01..07
        ],
      },
    ],
  },
]);
