// TypeScript mirror of the backend Pydantic schemas (see backend/src/riskapp/schemas.py).

export interface Department {
  id: number;
  name: string;
}

export interface ProjectType {
  id: number;
  name: string;
}

export interface Project {
  id: number;
  project_code: string;
  name: string;
  customer: string | null;
  department_name: string;
  project_type_name: string;
  status: string;
  pm_user_id: number | null;
  start_date: string | null;
  end_date: string | null;
  stage_gate: string | null;
  closed_date: string | null;
  closed_by_user_id: number | null;
  risk_count: number;
  risk_ids: number[];
  risk_codes: string[];
}

export type Likelihood = 'Low' | 'Medium' | 'High';
export type Impact = 'Low' | 'Medium' | 'High';
export type RiskSource = 'Human' | 'Environmental' | 'Technical';
export type ResponseStrategy = 'Mitigate' | 'Transfer' | 'Avoid' | 'Accept';

export interface Risk {
  id: number;
  risk_code: string;
  project_id: number;
  description: string;
  category: string | null;
  subcategory: string | null;
  risk_source: string | null;
  likelihood: string;
  impact: string;
  risk_rating: string;
  response_strategy: string | null;
  response_plan: string | null;
  owner_user_id: number | null;
  status: string;
  source: string | null;
  raised_by: string | null;
  identified_during: string | null;
  source_file_name: string | null;
  source_file_url: string | null;
  source_risk_id: string | null;
  llm_analysis: string | null;
  risk_start_date: string | null;
  risk_end_date: string | null;
  sla_deadline: string | null;
  sla_acknowledged: boolean;
  sla_manual_override: boolean;
  accepted_date: string | null;
  resolved_date: string | null;
  closed_date: string | null;
  root_cause: string | null;
  what_worked: string | null;
  resolution_category: string | null;
  created_at: string;
}

export interface RiskAuditLog {
  id: number;
  risk_id: number;
  user_id: number | null;
  action: string;
  field: string | null;
  old_value: unknown;
  new_value: unknown;
  created_at: string;
}

export interface Notification {
  id: number;
  recipient_user_id: number | null;
  type: string;
  title: string;
  body: string;
  risk_id: number | null;
  project_id: number | null;
  read: boolean;
  created_at: string;
}

/** GET /api/me — the current caller's identity and roles. */
export interface Me {
  user_id: number | null;
  upn: string;
  roles: string[];
}

export interface SuggestedRisk {
  risk_id: string;
  source_file: string;
  source_file_url: string;
  source_risk_id: string | null;
  description: string;
  match_type: string;
  match_count: number | null;
  similarity: number | null;
  citation: string;
  analysis: string | null;
  likelihood: string | null;
  impact: string | null;
  risk_rating: string | null;
  category: string | null;
}

export interface ProjectCreatePayload {
  name: string;
  department: string;
  project_type: string;
  customer?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  stage_gate?: string | null;
  pm_upn?: string | null;
}

export interface RiskCreatePayload {
  project_id: number;
  description: string;
  category?: string | null;
  subcategory?: string | null;
  risk_source?: RiskSource | null;
  likelihood: Likelihood;
  impact: Impact;
  response_strategy?: ResponseStrategy | null;
  response_plan?: string | null;
  owner_user_id?: number | null;
  risk_start_date?: string | null;
  risk_end_date?: string | null;
  source?: 'Historical' | 'Custom' | 'Kickoff' | null;
  identified_during?: string | null;
}
