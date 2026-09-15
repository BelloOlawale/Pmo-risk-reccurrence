PMO Risk Automation
End-to-End Process Flow & Architecture
Detailed functional, automation, SLA, escalation, reporting and Azure architecture document
Version: 1.0 | Date: 24 August 2026
1. Purpose
This document defines the complete end-to-end process for the PMO Risk Automation solution. It describes how a project enters the platform, how AI-supported risk suggestions are generated and dispositioned, how accepted risks become the project's risk register, how ownership and SLA acknowledgement are managed, how missed SLAs trigger escalation and issue materialization, and how weekly PMO summaries are produced.
The solution is designed around a React web application, FastAPI API layer, PostgreSQL transactional data store, Redis for asynchronous job brokering/caching, Azure Container Apps for the FastAPI web app plus Celery Worker and Celery Beat, Azure Blob Storage for historical/source files, Azure OpenAI for AI capabilities, Microsoft Entra ID for authentication, and Azure Communication Services for notification delivery.
2. Executive Process Overview
 
Figure 1. End-to-end business process from project onboarding through risk lifecycle and escalation.
3. Actors and Responsibilities
Actor	Responsibility
Project Manager (PM)	Onboards projects; reviews suggested risks; accepts/dismisses suggestions; completes risk information; assigns risks; acknowledges/monitors ownership; receives weekly project summary.
Risk Owner	Owns assigned risk; receives assignment notification; acknowledges SLA on/after the risk start date; executes the response plan; works the risk through resolution.
Practice Lead	Receives assignment and escalation visibility; provides practice-level oversight.
PMO Lead	Provides PMO governance; receives assignment copies, escalations and weekly summary copies; monitors portfolio-level risk performance.
AI / Risk Intelligence Layer	Generates candidate risk suggestions using project attributes and historical risk information; supports similarity/recurrence intelligence and explanatory content.
Celery Worker	Executes asynchronous notifications, SLA checks, escalation processing, weekly aggregation/reporting and other background work.
Celery Beat	Triggers scheduled jobs such as SLA monitoring and the weekly Monday 08:00 summary.
4. Project Onboarding
The lifecycle begins when the Project Manager creates/onboards a project in the PMO application.
•	Project metadata is entered and validated through the React interface.
•	FastAPI receives the authenticated request and applies validation and business rules.
•	The project record is persisted in PostgreSQL and becomes eligible for risk suggestion.
•	The project is associated with its Project Manager and relevant organisational/practice context.
•	Once onboarding is complete, the risk suggestion process is initiated.
5. AI Risk Suggestion Process
After onboarding, the platform evaluates the new project against available historical risk information and project attributes. The AI layer can use Azure OpenAI and supporting embedding/similarity or recurrence logic to identify risks that are relevant to the project.
1.	Retrieve applicable project attributes and historical risk context.
2.	Prepare the input context for the AI/risk intelligence layer.
3.	Generate candidate risks with descriptions and relevant categories/lifecycle context.
4.	Present suggestions to the Project Manager in the application.
5.	Each suggestion exposes an explicit Accept or Dismiss action.
6. Accept vs Dismiss Decision
The Project Manager controls which AI suggestions become governed project risks.
Decision	Destination	Outcome
Accept	Active Risk Register	A governed risk record is created for the project and proceeds through completion, assignment and SLA management.
Dismiss	Suggestions Dismissed	The suggestion is retained for traceability but does not become an active risk in the project risk register.
7. Risk Register Data Model
Every accepted risk contains the following core attributes:
Field	Purpose
Risk ID	Unique identifier for the risk.
Description	Clear statement of the risk/event and its potential effect.
Category	Risk classification/category.
Lifecycle Stage	Project lifecycle stage in which the risk applies.
Impact	Impact assessment.
Likelihood	Likelihood assessment.
Risk Rating	Calculated/assigned risk severity based on the risk assessment.
Response Strategy	Selected treatment strategy.
Response Plan	Specific actions required to manage the risk.
Risk Start Date	Date from which the risk/SLA workflow becomes active.
Risk End Date	Expected end date or risk validity boundary.
SLA Deadline	Latest point by which the required acknowledgement must be completed.
SLA Manual Override	Manual control allowing the authorised user to override the default SLA deadline.
Risk Status	Current lifecycle state such as Accepted, InProgress, Escalated, Materialized or Resolved.
Risk Owner	Person accountable for managing the risk.
8. Risk Assignment & Notification
6.	Once all required risk attributes are populated, the Project Manager assigns the risk to a Risk Owner.
7.	The assignment is persisted against the risk record.
8.	An immediate notification is sent to the Risk Owner.
9.	The notification copies the Practice Lead, PMO Lead and Project Manager so that ownership is visible from the beginning.
10.	The risk remains governed through its lifecycle while the owner executes the response plan.
9. SLA Acknowledgement Lifecycle
 
Figure 2. SLA acknowledgement and escalation decision path.
On the Risk Start Date, the system sends another notification to the Risk Owner. The owner must enter the application and acknowledge the SLA. A successful acknowledgement records the SLA as satisfied/compliant and allows the risk to continue under normal monitoring.
10. SLA Deadline & Escalation
The escalation mechanism is time-driven. The platform checks outstanding SLA acknowledgements using scheduled/background processing. The SLA deadline is calculated from the configured SLA and can be manually overridden where authorised.
11.	At or before the deadline: if the owner has acknowledged, no escalation occurs.
12.	After the deadline: if acknowledgement is still absent, the risk status changes to Escalated.
13.	An escalation email is sent to the PMO Lead, Project Manager and Practice Lead.
14.	The escalation is treated as a governance exception rather than merely a notification.
15.	That escalated risk becomes an issue: the Issues table is populated with the relevant risk attributes and risk description.
16.	The issue is then assigned to another owner for follow-up and resolution.
11. Risk-to-Issue Materialization
Issue materialization preserves the context of the original risk while creating a separate work item for escalated management. The issue record should carry enough risk attributes to allow the recipient to understand the original exposure without repeatedly navigating back to the risk.
•	Source Risk ID/reference
•	Risk Description
•	Category and Lifecycle Stage
•	Impact, Likelihood and Risk Rating
•	Response Strategy and Response Plan
•	Risk Start/End Dates
•	SLA information and escalation state
•	Original Risk Owner and new Issue Owner where applicable
•	Relevant timestamps for auditability
12. Risk Lifecycle & Status Bands
Status	Meaning	Typical transition
Accepted	Risk has been accepted into the governed risk register.	Suggestion accepted → Accepted
InProgress	Risk treatment/management activity is underway.	Accepted → InProgress
Escalated	SLA acknowledgement was missed by the configured deadline.	InProgress/active → Escalated
Materialized	Risk has occurred/converted into an issue or material event, depending on the implemented workflow.	Active risk → Materialized
Resolved	Risk has been successfully treated/closed.	InProgress/Materialized → Resolved
13. Weekly PMO Summary Automation
 
Figure 3. Scheduled weekly summary generation and delivery.
A weekly summary is preferably generated every Monday at 08:00. Celery Beat triggers the scheduled job, Celery Worker performs the aggregation, and Azure Communication Services delivers the structured email.
17.	For each active project, aggregate Active Risks.
18.	Count risks by status band: Accepted, InProgress, Escalated, Materialized and Resolved.
19.	Calculate resolution rate.
20.	Calculate SLA compliance percentage.
21.	Calculate average Resolution Duration.
22.	Identify risks approaching their deadline, defined as less than 24 hours remaining.
23.	Identify risks with no SLA configured.
24.	Compile the project-specific summary into a structured email.
25.	Send To: Project Manager; CC: PMO Lead.
14. Weekly KPI Definitions
Metric	Definition
Status counts	Number of active-project risks in each configured status band.
Resolution rate	Resolved risks divided by the relevant risk population, expressed as a percentage.
SLA compliance %	Risks whose required SLA acknowledgement was completed within the applicable deadline divided by risks subject to SLA, expressed as a percentage.
Average Resolution Duration	Average elapsed duration between the defined risk-resolution start timestamp and resolution timestamp for resolved risks.
Deadline <24h flag	Open risks with less than 24 hours remaining before the SLA deadline.
No-SLA flag	Risks where an SLA deadline has not been configured and no manual override/default has produced one.
15. Notification Matrix
Trigger	Primary recipient	CC	Purpose
Risk assigned	Risk Owner	Practice Lead; PMO Lead; Project Manager	Inform owner and governance stakeholders of new accountability.
Risk Start Date	Risk Owner	—	Prompt SLA acknowledgement in the application.
SLA deadline missed	PMO Lead	Project Manager; Practice Lead	Escalate overdue/unacknowledged risk.
Weekly summary	Project Manager	PMO Lead	Provide project-level risk metrics and actionable flags.
16. Architectural Diagram
 
Figure 4. Target Azure architecture for the PMO automation solution.
17. Architecture Component Responsibilities
Component	Role
React Web Application	User interface for project onboarding, risk review, risk register management, assignment and SLA acknowledgement. Authenticates users through Microsoft Entra ID/MSAL.
FastAPI	Primary backend/API. Handles authenticated API requests, validation, business rules, persistence orchestration and lifecycle transitions. Azure Functions are not required in this architecture.
PostgreSQL	System of record for structured PMO entities including projects, risks, issues, ownership, SLA information, statuses and reporting data.
Azure Container Apps	Compute layer hosting the FastAPI web application, Celery Worker and Celery Beat.
Redis	Cache and Celery message broker used to coordinate asynchronous/background processing.
Celery Worker	Executes background jobs such as SLA monitoring, escalation, notifications, AI processing and weekly reporting.
Celery Beat	Schedules recurring jobs, including the Monday 08:00 summary and periodic SLA checks.
Azure Blob Storage	Stores historical risk-register files, Excel/source datasets and other unstructured source material used by the intelligence layer.
Azure OpenAI	Provides generative AI capabilities for risk suggestions, explanation/summarisation and related intelligence tasks.
Embeddings / Similarity Layer	Converts text into vectors so historical risks and project/risk descriptions can be compared for semantic similarity and recurrence support.
Microsoft Entra ID	Provides identity and authentication for the React application and token validation at the FastAPI layer.
Azure Communication Services	Delivers operational email notifications for assignments, SLA reminders, escalations and weekly summaries.
Application Insights / Azure Monitor	Provides observability into API requests, background jobs, failures, performance and operational health.
18. End-to-End Technical Sequence
1. User signs in through Entra ID and receives an authenticated token.
2. React sends the authenticated request to FastAPI.
3. FastAPI validates the token, validates project data and writes the project to PostgreSQL.
4. The application initiates risk intelligence processing using historical data and project context.
5. Historical/source files are read from Blob Storage where required; structured risk history is read from PostgreSQL.
6. Azure OpenAI and the supporting similarity/embedding logic produce candidate risk suggestions.
7. Suggestions are displayed in React with Accept/Dismiss controls.
8. Accept writes a governed risk record to PostgreSQL; Dismiss writes/retains the suggestion in the dismissed-suggestions area.
9. PM completes the risk attributes and assigns a Risk Owner.
10. FastAPI records the assignment and queues an asynchronous notification job through Redis/Celery.
11. Celery Worker sends the assignment notification through Azure Communication Services.
12. Celery Beat runs SLA monitoring on the configured schedule.
13. On the Risk Start Date, the notification job alerts the Risk Owner to acknowledge the SLA.
14. If acknowledgement occurs before the deadline, the risk is marked SLA satisfied/compliant.
15. If the deadline passes without acknowledgement, the worker transitions the risk to Escalated and sends the escalation email.
16. The escalation workflow creates/populates an Issue from the risk attributes and description and assigns the issue to another owner.
17. Weekly, Celery Beat triggers the Monday 08:00 summary job.
18. Celery Worker aggregates active-project risk KPIs and exception flags and sends the structured summary email.
19. Data & State Flow
The logical state progression is:
Project → Risk Suggestions → Accepted Risk Register → Assigned Risk → SLA Due → SLA Satisfied → Normal Monitoring → Resolved
Project → Risk Suggestions → Dismissed Suggestions
Assigned Risk → SLA Deadline Missed → Escalated Risk → Issue Created → New Owner → Resolution
20. Controls, Auditability & Governance
•	Every risk should retain a stable Risk ID and project association.
•	Accept/Dismiss decisions should be traceable to the user and timestamp.
•	Risk assignment should be auditable, including previous and current owner where reassignment occurs.
•	SLA deadline calculations should preserve whether the deadline was system-derived or manually overridden.
•	Escalation should be idempotent so a single overdue risk does not generate repeated issue records or duplicate escalation events.
•	Status transitions should be timestamped to support resolution-duration and SLA-compliance reporting.
•	Notification jobs should be retryable and should log success/failure for operational troubleshooting.
•	AI-generated suggestions should remain recommendations until explicitly accepted by the Project Manager.
•	Access should be role-aware so users only manage projects and risks for which they are authorised.
21. Exception & Failure Handling
Scenario	Expected handling
AI suggestion failure	Project onboarding remains intact; suggestion generation failure is logged and surfaced for retry/manual review.
Notification delivery failure	Background job retries according to configured policy and records delivery failure for operational follow-up.
Redis/Celery job failure	The transactionally stored risk remains in PostgreSQL; the asynchronous job can be retried without recreating the risk.
Duplicate escalation attempt	Use an escalation flag/timestamp or equivalent idempotency control before creating an issue or sending the escalation notification.
Missing SLA	Risk is flagged in the weekly summary as 'No SLA set' and should be reviewed by the Project Manager.
Approaching deadline	Risks with less than 24 hours remaining are highlighted in the weekly summary for proactive action.
22. Implementation Summary
The PMO automation is a closed-loop risk governance platform: it starts with project onboarding, uses AI to accelerate identification of likely risks, requires human acceptance before risks enter the governed register, enforces ownership and SLA acknowledgement, escalates exceptions automatically, converts missed-SLA risks into actionable issues, and provides a recurring management view through weekly reporting.
The architecture separates interactive API work from scheduled/background processing. React and FastAPI handle the user-facing workflow; PostgreSQL stores authoritative business data; Redis and Celery handle asynchronous execution and scheduling; Blob Storage retains historical/unstructured inputs; Azure OpenAI supports intelligence; Entra ID secures access; Azure Communication Services handles operational email; and Azure Container Apps provides the compute environment.
