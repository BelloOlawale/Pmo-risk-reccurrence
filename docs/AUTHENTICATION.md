# Authentication

How sign-in works for PMO Risk Intelligence, and how to provision app-managed
accounts. For deployment commands see [`infra/RUNBOOK.md`](../infra/RUNBOOK.md).

## 1. Sign-in model

Sign-in is **config-driven** — no code changes to switch. The API accepts these
identities in order (`get_principal` in `backend/src/riskapp/auth.py`):

| # | Method | When it is active | Who it is for |
|---|--------|-------------------|---------------|
| 1 | **Entra ID SSO** | `RISKAPP_ENTRA_TENANT_ID` set | Staff with a Microsoft 365 account |
| 2 | **App-managed email + password** | `RISKAPP_LOCAL_LOGIN_ENABLED=true` | People who need access without Entra |
| 3 | **Header identity** | `RISKAPP_ALLOW_HEADER_AUTH=true` and no tenant | Automated tests / local tooling only |

If none are configured the API returns **401 for every request**. It never trusts
client-supplied roles.

The SPA offers exactly one method per build, chosen by the build-time
`VITE_AUTH_MODE` value:

| `VITE_AUTH_MODE` | Sign-in page |
|---|---|
| `entra` | "Sign in with Microsoft" button (MSAL redirect) |
| `password` | Email + password form |

> Entra and app-managed passwords can both be enabled on the **backend** at the
> same time (the API tries a local token first, then Entra), but the **frontend
> shows one or the other**. Showing both buttons is a small UI change — ask if
> you need it.

## 2. Entra ID SSO (Microsoft)

1. The SPA redirects to Microsoft (`loginRedirect`) with scopes
   `openid profile email api://{clientId}/.default`.
2. The returned OIDC access token is sent as `Authorization: Bearer <token>`.
3. The API validates the RS256 signature (tenant JWKS), issuer (`.../v2.0`) and
   audience (client id).
4. Roles come from the token's **`groups` claim**, mapped through
   `RISKAPP_ENTRA_ROLE_GROUP_IDS`, e.g.

   ```json
   {"System Admin":"<group-id>","PMO Lead":"<group-id>","Project Manager":"<group-id>"}
   ```

5. The caller's UPN is resolved to (or created as) a `users` row.

Someone with a valid Microsoft account but no mapped group gets an authenticated
but **role-less** session (no privileges).

## 3. App-managed email + password (local accounts)

The application holds the password itself. This is the method to use when Entra
admin consent is unavailable or when people have no M365 account.

### How it works

1. `RISKAPP_LOCAL_LOGIN_ENABLED=true` on the API and the SPA built with
   `VITE_AUTH_MODE=password`.
2. The user enters their **email** and **password** on the sign-in page.
3. `POST /api/auth/login` checks the credentials against the `users` row and
   returns a signed **bearer token** (HS256, 8-hour lifetime).
4. Every later API call sends that bearer token; the API resolves the role from
   the user's stored `role` column.

### Password storage — important

- Passwords are hashed with **scrypt** (per-password random salt, from the
  Python standard library — see `backend/src/riskapp/security.py`).
- Only the hash (`users.password_hash`) is stored. **No one — not even an
  administrator or the database — can read a password back.** There is no
  "show password" anywhere.
- Because of that, a provisioned password is known **only** at the moment it is
  created. It must be captured then and delivered to the person out-of-band.
- Password changes: on first sign-in an administrator-provisioned account is
  **forced to set its own password** before any application screen is shown
  (`must_change_password`). This is done from the "Set your password" screen,
  which calls `POST /api/auth/change-password`. Administrators can also reset
  someone later via `POST /api/users/{id}/credentials` (which forces another
  change).
- Minimum length is 8 characters (enforced by the API and provisioning tool).

### Roles

Each local account carries exactly one role, stored on the user row:

| Role | Authority (summary) |
|---|---|
| **System Admin** | Everything, including user onboarding |
| **PMO Lead** | Portfolio-wide visibility, close projects/risks, assign PMs |
| **Project Manager** | Own projects/registers; accept/dismiss suggestions; own risks |

## 4. Provisioning local accounts

Accounts are created from a CSV so a batch of people can be mapped at once.
Passwords are either **generated per person** (recommended) or supplied in the
CSV.

### 4.1 CSV format

Header row required; column names are case-insensitive. `role` and `password`
are optional.

```csv
email,name,role
ada.lovelace@wragbysolutions.com,Ada Lovelace,System Admin
sam.bello@wragbysolutions.com,Sam Bello,PMO Lead
john.doe@wragbysolutions.com,John Doe,Project Manager
```

- `role` defaults to **Project Manager** when omitted or blank.
- `password` (optional column) is used verbatim when present; blank cells fall
  back to a generated password.
- `email` is matched case-insensitively against existing rows — so if the Entra
  directory sync already created the person, this **promotes that same row**
  to a local account rather than duplicating it.

### 4.2 Run the provisioner

```bash
cd app/backend
.venv/Scripts/python.exe -m riskapp.provision_users \
    --file ../../people.csv \
    --out  ../../provisioned-credentials.csv
```

Options:

| Option | Meaning |
|---|---|
| `--file <path>` | Input CSV (**required**) |
| `--out <path>` | Where to write the one-time credentials CSV (default `provisioned-credentials.csv`) |
| `--dry-run` | Validate and report without writing anything |
| `--no-passwords` | Do not write the credentials file (e.g. passwords already shared) |

The output file contains `email,name,role,password` for the batch and is written
with owner-only permissions. Deliver each row to its person through a secure
channel (password manager invitation, encrypted message, or in person), then
**delete the file**.

### 4.4 Forced password change on first sign-in

Provisioned accounts (and any account whose password an admin resets) are
created with `must_change_password = true`. On the next sign-in:

1. The API returns the bearer token with `must_change_password: true`.
2. The SPA calls `GET /api/me` (which reports the same flag) and renders the
   **"Set your password"** screen instead of the app shell.
3. The user enters the temporary password plus their new password (twice).
4. `POST /api/auth/change-password` stores the new scrypt hash and clears the
   flag; the app then loads normally.

The temporary password is invalid immediately after the change. If a user
forgets their password, an admin resets it (section 4.4) and the forced-change
flow starts again.

### 4.5 Single account (alternative)

```bash
.venv/Scripts/python.exe -m riskapp.set_password \
    --upn ada.lovelace@wragbysolutions.com \
    --display-name "Ada Lovelace" \
    --role "System Admin"
```

It prompts twice for the password and stores only the hash.

### 4.6 Self-service / admin reset (API)

| Endpoint | Who | Purpose |
|---|---|---|
| `POST /api/auth/change-password` | Any signed-in local user | Change own password (requires current password) |
| `POST /api/users/{id}/credentials` | System Admin / PMO Lead | Reset someone's password and/or role |

## 5. Enabling it in `int`

1. Provision the accounts (section 4) **first** while SSO is still the live
   method — this avoids locking anyone out.
2. Set the runtime flag in `infra/deploy.int.env`:
   `RISKAPP_LOCAL_LOGIN_ENABLED=true`.
3. Build the SPA for password sign-in: add `VITE_AUTH_MODE=password` to
   `infra/deploy.int.env`.
4. Deploy: `bash infra/deploy-service.sh int --allow-local-login`.
   The `--allow-local-login` flag is the deliberate acknowledgement that
   app-managed passwords bypass Entra MFA/Conditional Access; the deploy refuses
   without it.
5. Distribute the generated passwords, then delete the credentials file.

> Changing `VITE_AUTH_MODE`/`VITE_ENTRA_*` requires a **frontend rebuild**.
> Changing `RISKAPP_LOCAL_LOGIN_ENABLED`/`RISKAPP_ENTRA_*` requires a **backend
> deploy**.

## 6. External risk owners

Partners/vendors captured as **external owners** never sign in and have no
password. They act through a **signed acknowledgement link**
(`/acknowledge/{token}`) emailed to them; the link is bound to their owner id and
risk id.
