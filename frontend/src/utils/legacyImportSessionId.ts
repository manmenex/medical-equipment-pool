// Roadmap PR20F: routes the session detail page to the correct client
// (real Equipment Master vs the PR19B mock, services/legacyImportClient.ts)
// without ever needing to know a session's dataset_type ahead of time.
// Every real backend ImportSession id is a UUID (`session_id: uuid.UUID`
// path param, backend/app/api/v1/import_sessions.py); every mock/fixture
// id (services/legacyImportFixtures.ts, e.g. "demo-completed", "preview-3")
// is deliberately never UUID-shaped. This is routing/infrastructure only
// -- it never inspects or decides anything about the session's own
// business data.
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isBackendSessionId(sessionId: string | undefined): boolean {
  return Boolean(sessionId && UUID_PATTERN.test(sessionId));
}
