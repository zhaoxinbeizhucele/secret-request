# Secret Request
<!-- impeccable:product-schema 1 -->

## Platform
web

## Stack
Python client, TypeScript Cloudflare Worker with one SQLite Durable Object, same-origin HTML/CSS/JavaScript, short-lived Windows/macOS notification helpers, client-owned webhook.

## Users
People using local or remote agents who need to supply short-lived credentials. Service can be self-hosted or shared; recipients use a trusted HTTPS browser page.

## Product Purpose
An agent describes the task and required fields. A notification opens the request. The user submits encrypted values or declines. A local task program uses them without placing values in model-visible output.

## Operating Context
Client starts on demand and waits only for its own request. Browser is responsive on desktop and phone. Native notifications require an interactive desktop; webhook works on remote machines. Initialization needs a trusted service URL and notification settings; there is no account, device enrollment, pairing or long-lived service token.

## Capabilities and Constraints
One submission and one ciphertext collection. Multiple labelled fields. Memory-only local session expires after five idle minutes, renewed by accepted task executions and restarted after each execution ends. Status checks do not renew. No login, tenant management, global request list, server-owned notifications or long-term secret storage in this MVP.

## Product Principles
- Show the self-declared Agent, purpose, request time and remaining input time before asking for values.
- Keep input focused on submit or decline; attempt close only after acknowledged submission.
- Separate per-request input and retrieval permission.
- Keep native UI limited to notifications opening the shared web form.
- Reuse the current task session, revoke when done, and suppress task output containing credentials.
