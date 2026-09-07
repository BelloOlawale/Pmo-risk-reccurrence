import { Navigate, Route, Routes } from 'react-router-dom';

import { Layout } from './components/Layout';
import { ActiveRiskRegisterPage } from './pages/ActiveRiskRegisterPage';
import { OnboardProjectPage } from './pages/OnboardProjectPage';
import { PortfolioDashboardPage } from './pages/PortfolioDashboardPage';
import { ProjectDashboardPage } from './pages/ProjectDashboardPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { RiskCatalogPage } from './pages/RiskCatalogPage';
import { RiskDetailPage } from './pages/RiskDetailPage';
import { RiskRegistersPage } from './pages/RiskRegistersPage';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<RiskRegistersPage />} />
        <Route path="/active-register" element={<ActiveRiskRegisterPage />} />
        <Route path="/catalog" element={<RiskCatalogPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/:projectId" element={<ProjectDashboardPage />} />
        <Route path="/risks/:riskId" element={<RiskDetailPage />} />
        <Route path="/onboard" element={<OnboardProjectPage />} />
        <Route path="/portfolio" element={<PortfolioDashboardPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
