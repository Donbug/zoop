// 관리자 패널 진입점. App.tsx가 React.lazy로 불러오므로 이 파일 아래 코드는 사용자 번들에 들어가지 않는다.
import { Link, Route, Routes } from "react-router";
import { EmptyState } from "@/components/ui/feedback";
import { AdminLayout } from "./layout";
import { AdminAiPage } from "./pages/ai";
import { AdminAuditPage } from "./pages/audit";
import { AdminBriefingsPage } from "./pages/briefings";
import { AdminDashboardPage } from "./pages/dashboard";
import { AdminFeedbackPage } from "./pages/feedback";
import { AdminLoginPage } from "./pages/login";
import { AdminMemberDetailPage } from "./pages/member-detail";
import { AdminMembersPage } from "./pages/members";
import { AdminPipelinePage } from "./pages/pipeline";
import { AdminStatsPage } from "./pages/stats";
import { AdminCompanyStatsPage } from "./pages/stats-company";
import { AdminTranscriptPage } from "./pages/transcript";
import { RequireAdmin } from "./session";

export default function AdminRoot() {
  return (
    <Routes>
      <Route path="login" element={<AdminLoginPage />} />
      <Route
        element={
          <RequireAdmin>
            <AdminLayout />
          </RequireAdmin>
        }
      >
        <Route index element={<AdminDashboardPage />} />
        <Route path="pipeline" element={<AdminPipelinePage />} />
        <Route path="ai" element={<AdminAiPage />} />
        <Route path="briefings" element={<AdminBriefingsPage />} />
        <Route path="audit" element={<AdminAuditPage />} />
        <Route path="stats" element={<AdminStatsPage />} />
        <Route path="stats/companies/:id" element={<AdminCompanyStatsPage />} />
        <Route path="feedback" element={<AdminFeedbackPage />} />
        <Route path="feedback/transcripts/:id" element={<AdminTranscriptPage />} />
        <Route path="members" element={<AdminMembersPage />} />
        <Route path="members/:id" element={<AdminMemberDetailPage />} />
        <Route
          path="*"
          element={
            <EmptyState
              title="찾는 관리자 화면이 없어요"
              action={
                <Link to="/admin" className="font-medium text-brand-primary hover:underline">
                  대시보드로 가기
                </Link>
              }
            />
          }
        />
      </Route>
    </Routes>
  );
}
