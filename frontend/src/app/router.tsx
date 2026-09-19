import { createBrowserRouter } from "react-router-dom";

import { HomeRedirect } from "@/app/HomeRedirect";
import { AppShell } from "@/app/layout/AppShell";
import { RequireAuth } from "@/app/RequireAuth";
import { StatusPage } from "@/app/StatusPage";
import { AssistantPage } from "@/features/assistant/pages/AssistantPage";
import { AcceptInvitationPage } from "@/features/auth/pages/AcceptInvitationPage";
import { LoginPage } from "@/features/auth/pages/LoginPage";
import { ResetPasswordPage } from "@/features/auth/pages/ResetPasswordPage";
import { MyAssessmentPage } from "@/features/me/pages/MyAssessmentPage";
import { MyProfilePage } from "@/features/me/pages/MyProfilePage";
import { StudentHomePage } from "@/features/me/pages/StudentHomePage";
import { OverviewPage } from "@/features/overview/pages/OverviewPage";
import { PeoplePage } from "@/features/people/pages/PeoplePage";
import { ProjectListPage } from "@/features/projects/pages/ProjectListPage";
import { ProjectPage } from "@/features/projects/pages/ProjectPage";
import { ReportEditorPage } from "@/features/report/pages/ReportEditorPage";
import { ReportReaderPage } from "@/features/report/pages/ReportReaderPage";
import { ReviewPage } from "@/features/review/pages/ReviewPage";
import { StudentProfilePage } from "@/features/students/pages/StudentProfilePage";
import { WorkspacesPage } from "@/features/workspaces/pages/WorkspacesPage";

// Routes follow docs/architecture.md §4.2. The role guard keeps the UI from offering a page the
// caller cannot load; the API enforces every permission itself (AUTH-02).
export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/login", element: <LoginPage /> },
      // Public by necessity: the invitation token is the credential, and the person holding it
      // has no session yet — that is the whole point of the page (AUTH-01).
      { path: "/accept-invitation", element: <AcceptInvitationPage /> },
      { path: "/reset-password", element: <ResetPasswordPage /> },
      { path: "/status", element: <StatusPage /> },
      {
        element: <RequireAuth />,
        children: [
          // "/" and anything unrecognised go to the home for this role, not to a fixed page.
          { path: "/", element: <HomeRedirect /> },
          { path: "*", element: <HomeRedirect /> },
          // The list is what gives UI-03 a way in: until it existed nothing linked to the
          // project workspace. Both are signed-in rather than professor-only, because a student
          // is on the projects they report against.
          { path: "/projects", element: <ProjectListPage /> }, // PROJ-01
          { path: "/projects/:id", element: <ProjectPage /> }, // UI-03
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
          // What was actually submitted, as against the draft the editor shows. REP-02, REP-05.
          { path: "/report/:periodId/submitted", element: <ReportReaderPage /> },
          // The destination the professor's "publish to the student" has always named.
          { path: "/me/profile", element: <MyProfilePage /> }, // UI-02, UI-04
          { path: "/me/assessments/:assessmentId", element: <MyAssessmentPage /> }, // UI-02
        ],
      },
      {
        element: <RequireAuth role="prof" />,
        children: [
          { path: "/overview", element: <OverviewPage /> }, // UI-01
          { path: "/people", element: <PeoplePage /> }, // AUTH-01
          { path: "/workspaces", element: <WorkspacesPage /> }, // ADR 0012
          { path: "/students/:id", element: <StudentProfilePage /> }, // UI-04
          // The read half of REP-02..05, which had no surface at either end until now.
          { path: "/students/:studentId/reports/:periodId", element: <ReportReaderPage /> },
          { path: "/review/:assessmentId", element: <ReviewPage /> }, // UI-05
          { path: "/assistant", element: <AssistantPage /> }, // QA-01..07
        ],
      },
    ],
  },
]);
