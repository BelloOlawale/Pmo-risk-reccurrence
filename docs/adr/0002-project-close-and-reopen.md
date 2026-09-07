# Project closure and reopen are explicit, guarded actions

A Project Manager closes a Project, but the system blocks closure while any
Project Risk on it is not yet Resolved or Closed (the PM resolves/closes those
first). Reopening is a separate, explicit action that returns the Project to
Active, and risks cannot be added to a Closed Project. Chosen so the invariant
"a closed project has no open risks" always holds, which keeps the Active Risk
Register rule (Project Active AND risk not Resolved/Closed) consistent.
