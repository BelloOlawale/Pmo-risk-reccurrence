import { Navigate, Route, Routes } from 'react-router-dom';

import { Layout } from './components/Layout';
import { OnboardProjectPage } from './pages/OnboardProjectPage';
import { PortfolioDashboardPage } from './pages/PortfolioDashboardPage';
import { ProjectDashboardPage } from './pages/ProjectDashboardPage';
import { ProjectListPage } from './pages/ProjectListPage';
import { RiskDetailPage } from './pages/RiskDetailPage';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<ProjectListPage />} />
        <Route path="/projects/:projectId" element={<ProjectDashboardPage />} />
        <Route path="/risks/:riskId" element={<RiskDetailPage />} />
        <Route path="/onboard" element={<OnboardProjectPage />} />
        <Route path="/portfolio" element={<PortfolioDashboardPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
