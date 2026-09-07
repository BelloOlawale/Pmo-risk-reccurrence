import { Navigate, Route, Routes, useParams } from 'react-router-dom';

import { Layout } from './components/Layout';
import { ActiveRiskRegisterPage } from './pages/ActiveRiskRegisterPage';
import { CreateRiskPage } from './pages/CreateRiskPage';
import { PortfolioDashboardPage } from './pages/PortfolioDashboardPage';
import { ProjectDashboardPage } from './pages/ProjectDashboardPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { RiskDetailPage } from './pages/RiskDetailPage';
import { RiskRegistersPage } from './pages/RiskRegistersPage';

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
