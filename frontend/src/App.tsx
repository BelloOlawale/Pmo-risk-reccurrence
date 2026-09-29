import { lazy } from 'react';
import { Navigate, Route, Routes, useParams } from 'react-router-dom';

import { Layout } from './components/Layout';
import { ActiveRiskRegisterPage } from './pages/ActiveRiskRegisterPage';
import { CreateRiskPage } from './pages/CreateRiskPage';
import { IssueDetailPage } from './pages/IssueDetailPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { RiskDetailPage } from './pages/RiskDetailPage';
import { RiskRegistersPage } from './pages/RiskRegistersPage';

// Chart-heavy dashboards pull in ECharts (~1 MB). Load them on demand so the
// first paint (register pages) ships a much smaller bundle. The Suspense
// boundary lives inside the app shell (see Layout), so the sidebar/topbar stay
// mounted while a page chunk downloads.
const PortfolioDashboardPage = lazy(() =>
  import('./pages/PortfolioDashboardPage').then((m) => ({ default: m.PortfolioDashboardPage })),
);
const ProjectDashboardPage = lazy(() =>
  import('./pages/ProjectDashboardPage').then((m) => ({ default: m.ProjectDashboardPage })),
);

function LegacyProjectRedirect() {
  const { projectId } = useParams();
  return <Navigate to={`/risk-history/${projectId ?? ''}`} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/active-risk" replace />} />
        <Route path="/create-risk" element={<CreateRiskPage />} />
        <Route path="/active-risk" element={<ActiveRiskRegisterPage />} />
        <Route path="/active-risk/:projectId" element={<ProjectDashboardPage />} />
        <Route path="/risk-history" element={<ProjectsPage />} />
        <Route path="/risk-history/:projectId" element={<ProjectDashboardPage />} />
        <Route path="/risks/:riskId" element={<RiskDetailPage />} />
        <Route path="/issues/:issueId" element={<IssueDetailPage />} />
        <Route path="/report" element={<PortfolioDashboardPage />} />

        {/* Internal utility route (not in the sidebar navigation). */}
        <Route path="/risk-register" element={<RiskRegistersPage />} />

        {/* Legacy redirects (kept so existing deep links keep working). */}
        <Route path="/active-register" element={<Navigate to="/active-risk" replace />} />
        <Route path="/projects" element={<Navigate to="/risk-history" replace />} />
        <Route path="/projects/:projectId" element={<LegacyProjectRedirect />} />
        <Route path="/onboard" element={<Navigate to="/create-risk" replace />} />
        <Route path="/portfolio" element={<Navigate to="/report" replace />} />

        <Route path="*" element={<Navigate to="/active-risk" replace />} />
      </Route>
    </Routes>
  );
}
