import type { DocumentStage } from './document-types';
import type {
  ApiResponse,
  DMConversation,
  EventPollResponse,
  KanbanTask,
  TaskRunInfo,
  Workflow,
  WorkflowStep,
  MessagePollResponse,
  NetworkDiscovery,
  NotificationItem,
  ONMEvent,
  OperatorRun,
  ShareSummary,
  TrashEntry,
  Workspace,
  WorkspaceAgent,
  WorkspaceFile,
  WorkspaceMe,

  WorkspaceSession,
} from './types';
import { eventToMessage } from './types';

import { API_URL } from './config';
import { AUTH_INVALID_EVENT, AUTH_UNVERIFIED_EVENT, currentIdToken, RecentSignInRequired } from './auth/service';

/** Map a snake_case custom-skill entry from the backend to camelCase. */
/** Map snake_case file response from backend to camelCase WorkspaceFile. */
function mapFileResponse(raw: Record<string, unknown>): WorkspaceFile {
  return {
    id: raw.id as string,
    filename: raw.filename as string,
    contentType: (raw.content_type || raw.contentType || 'application/octet-stream') as string,
    size: raw.size as number,
    uploadedBy: (raw.uploaded_by || raw.uploadedBy || 'unknown') as string,
    channelName: (raw.channel_name ?? raw.channelName ?? null) as string | null,
    status: (raw.status || 'active') as string,
    createdAt: (raw.created_at || raw.createdAt || null) as string | null,
  };
}

/** Map a snake_case trash entry from the backend to camelCase. */
function mapTrashEntry(raw: Record<string, unknown>): TrashEntry {
  return {
    trashId: raw.trash_id as string,
    kind: raw.kind === 'folder' ? 'folder' : 'file',
    path: (raw.path || '') as string,
    name: (raw.name || '') as string,
    deletedAt: (raw.deleted_at ?? null) as string | null,
    fileCount: (raw.file_count as number) ?? 0,
    size: (raw.size as number) ?? 0,
    files: ((raw.files as Record<string, unknown>[]) || []).map((f) => ({
      id: f.id as string,
      filename: f.filename as string,
      name: (f.name || f.filename) as string,
      size: (f.size as number) ?? 0,
      contentType: (f.content_type || 'application/octet-stream') as string,
      kind: (f.kind || 'other') as string,
    })),
  };
}

class WorkspaceApi {
  /**
   * The workspace MACHINE token. On Placement AI this is always empty: the
   * backend stopped handing it to the browser, because it is the credential
   * PAI's agents write with and it never expires. It stays here only for the
   * self-hosted OpenAgents flow, where the operator pastes their own token
   * into ?token= and there is no bearer to use instead.
   */
  private token: string = '';
  /** Signed in with Firebase: every request then carries a fresh ID token. */
  private signedIn = false;
  /** Short-lived, read-only. The only credential that goes into a URL. */
  private streamTicket: string = '';
  private workspaceId: string = '';

  configure(workspaceId: string, token: string, bearerToken?: string, streamTicket?: string) {
    this.workspaceId = workspaceId;
    this.token = token;
    if (bearerToken !== undefined) this.signedIn = !!bearerToken;
    if (streamTicket !== undefined) this.streamTicket = streamTicket;
  }

  reset() {
    this.workspaceId = '';
    this.token = '';
    this.signedIn = false;
    this.streamTicket = '';
  }

  private async authHeaders(): Promise<Record<string, string>> {
    const headers: Record<string, string> = {};
    if (this.token) headers['X-Workspace-Token'] = this.token;
    const idToken = this.signedIn ? await currentIdToken() : null;
    if (idToken) headers['Authorization'] = `Bearer ${idToken}`;
    return headers;
  }

  setStreamTicket(streamTicket: string) {
    this.streamTicket = streamTicket;
  }

  /**
   * The credential for URLs that cannot carry a header (EventSource, <img
   * src>, <a href>). Prefers the read-only ticket; falls back to the machine
   * token only on self-hosted, where that token is the operator's own and is
   * the only credential there is.
   */
  private urlCredential(params: URLSearchParams): URLSearchParams {
    if (this.streamTicket) params.set('ticket', this.streamTicket);
    else if (this.token) params.set('token', this.token);
    return params;
  }

  getSSEUrl(channelName: string): string {
    const params = this.urlCredential(new URLSearchParams({
      network: this.workspaceId,
      channel: channelName,
    }));
    return `${API_URL}/v1/events/stream?${params}`;
  }

  /** PAI Operator publishes run updates with target "core" (not a channel —
   * Operator has no thread of its own; see app/services/operator.py). This
   * is the realtime counterpart to listOperatorRuns() below: an exact-target
   * SSE stream so the "PAI is working…" indicator updates the instant a run
   * changes, instead of only on the next poll. */
  getOperatorEventsUrl(): string {
    const params = this.urlCredential(new URLSearchParams({
      network: this.workspaceId,
      target: 'core',
    }));
    return `${API_URL}/v1/events/stream?${params}`;
  }

  /** Whether configure() has run with a non-empty workspace id. */
  isConfigured(): boolean {
    return this.workspaceId !== '';
  }

  /**
   * Guard against firing requests before configure() has populated
   * workspaceId. configure() runs in a useEffect that fires *after* the
   * first render, so any event sent during initial mount would otherwise
   * POST `network: ""` and get a 400 ("Missing required field: network")
   * from the backend. Throw a clear error instead of a confusing 400.
   */
  private requireWorkspace(): string {
    if (this.workspaceId === '') {
      throw new Error('WorkspaceApi not configured yet (workspaceId is empty)');
    }
    return this.workspaceId;
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const json: ApiResponse<T> = await this.requestJson<ApiResponse<T>>(path, options);
    return json.data;
  }

  /** Like request(), but returns the body as-is (the PAI OS API has no {data} envelope). */
  private async requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
    // Merge pai-c + pai-os: pai-c's Firebase authHeaders() replaces pai-os's token/bearerToken block.
    const authHeaders = await this.authHeaders();
    const url = `${API_URL}${path}`;
    const res = await fetch(url, {
      ...options,
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders,
        ...options.headers,
      },
    });

    if (!res.ok) {
      const body = await res.text();
      if (res.status === 401 && typeof window !== 'undefined') {
        window.dispatchEvent(new Event(AUTH_INVALID_EVENT));
      }
      if (res.status === 403 && body.includes('AUTH_EMAIL_NOT_VERIFIED') && typeof window !== 'undefined') {
        window.dispatchEvent(new Event(AUTH_UNVERIFIED_EVENT));
      }
      throw new Error(`API ${res.status}: ${body}`);
    }

    return (await res.json()) as T;
  }

  // ---------------------------------------------------------------------------
  // PAI OS student inbox (backend/app/os, mounted only when OS_ENABLED)
  // ---------------------------------------------------------------------------

  async getOsInbox(): Promise<import('./os-inbox').OsInboxItem[]> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const body = await this.requestJson<{ items: import('./os-inbox').OsInboxItem[] }>(`/v1/os/inbox?${params}`);
    return body.items;
  }

  async completeOsInboxItem(id: number, payload: Record<string, unknown> = {}): Promise<{ completed: boolean }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/inbox/${id}/complete?${params}`, {
      method: 'POST', body: JSON.stringify({ payload }),
    });
  }

  /** PAI OS: the facts of the programmes in the student's plan (Slice 2 spec §4.8). */
  async getOsProgrammes(): Promise<import('./os-programmes').OsProgramme[]> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const body = await this.requestJson<{ programmes: import('./os-programmes').OsProgramme[] }>(`/v1/os/programmes?${params}`);
    return body.programmes;
  }

  /** PAI OS: the student's documents, their open findings and the document types (Slice 3 spec §4). */
  async getOsDocuments(): Promise<import('./os-documents').OsDocuments> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/documents?${params}`);
  }

  /**
   * PAI OS: upload one document. Multipart, so this is a bare fetch with the same auth headers and **no**
   * `Content-Type` (the browser sets the multipart boundary); requestJson would send application/json.
   */
  async uploadOsDocument(file: File, docType: string): Promise<import('./os-documents').OsDocument> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const form = new FormData();
    form.append('file', file);
    form.append('doc_type', docType);
    const headers: Record<string, string> = {};
    // Merge pai-c + pai-os: pai-c's Firebase auth headers (no bearerToken field any more).
    Object.assign(headers, await this.authHeaders());
    const res = await fetch(`${API_URL}/v1/os/documents?${params}`, {
      method: 'POST', body: form, headers, credentials: 'include', cache: 'no-store',
    });
    if (!res.ok) {
      if (res.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event(AUTH_INVALID_EVENT));
      const text = await res.text();
      let detail = text;
      try {
        detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
      } catch { /* not JSON: keep the text */ }
      throw new Error(`API ${res.status}: ${detail}`);
    }
    return (await res.json()) as import('./os-documents').OsDocument;
  }

  /** PAI OS: confirm or correct every field of one document. */
  async confirmOsDocument(id: number, fields: Record<string, unknown>): Promise<import('./os-documents').OsDocument> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/documents/${id}/confirm?${params}`, {
      method: 'POST', body: JSON.stringify({ fields }),
    });
  }

  /** PAI OS: choose the right value for a finding across documents. */
  async resolveOsFinding(id: number, value: unknown): Promise<import('./os-documents').OsFinding> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/documents/findings/${id}/resolve?${params}`, {
      method: 'POST', body: JSON.stringify({ value }),
    });
  }

  /** PAI OS: delete a document (its file and fields go; an audit row stays). */
  async deleteOsDocument(id: number): Promise<void> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const headers: Record<string, string> = {};
    // Merge pai-c + pai-os: pai-c's Firebase auth headers (no bearerToken field any more).
    Object.assign(headers, await this.authHeaders());
    const res = await fetch(`${API_URL}/v1/os/documents/${id}?${params}`, {
      method: 'DELETE', headers, credentials: 'include', cache: 'no-store',
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  }

  // ---------------------------------------------------------------------------
  // PAI OS self-serve start and eligibility (Slice 4 spec §4)
  // ---------------------------------------------------------------------------

  /** PAI OS: the student's eligibility change notes (the inbox's `notes`). */
  async getOsInboxNotes(): Promise<import('./os-self-serve').OsNote[]> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const body = await this.requestJson<{ notes?: import('./os-self-serve').OsNote[] }>(`/v1/os/inbox?${params}`);
    return body.notes ?? [];
  }

  /** PAI OS: mark an eligibility note read (204, no body). */
  async readOsNote(id: number): Promise<void> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const headers: Record<string, string> = {};
    // Merge pai-c + pai-os: pai-c's Firebase auth headers (no bearerToken field any more).
    Object.assign(headers, await this.authHeaders());
    const res = await fetch(`${API_URL}/v1/os/inbox/notes/${id}/read?${params}`, {
      method: 'POST', headers, credentials: 'include', cache: 'no-store',
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  }

  async getOsRoutes(): Promise<import('./os-self-serve').OsRoute[]> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const body = await this.requestJson<{ routes: import('./os-self-serve').OsRoute[] }>(`/v1/os/routes?${params}`);
    return body.routes;
  }

  /** PAI OS: the route's programmes, each with the student's eligibility card. */
  async getOsRouteProgrammes(route: string, intakeYear: number): Promise<import('./os-self-serve').OsRouteProgramme[]> {
    const params = new URLSearchParams({ network: this.requireWorkspace(), intake: String(intakeYear) });
    const body = await this.requestJson<{ programmes: import('./os-self-serve').OsRouteProgramme[] }>(
      `/v1/os/routes/${encodeURIComponent(route)}/programmes?${params}`);
    return body.programmes;
  }

  /** PAI OS: one programme's card, with up to 3 swap suggestions. */
  async getOsEligibility(programmeRef: string, route: string, intakeYear: number): Promise<import('./os-self-serve').OsEligibility> {
    const params = new URLSearchParams({ network: this.requireWorkspace(), route, intake: String(intakeYear) });
    return this.requestJson(`/v1/os/eligibility/${encodeURIComponent(programmeRef)}?${params}`);
  }

  /** PAI OS: the current pilot terms and whether the student agreed to them (Slice 9a spec §3.2). */
  async getOsConsent(): Promise<import('./os-consent').OsConsent> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/consent?${params}`);
  }

  /** PAI OS: agree to this version of the pilot terms (204, no body; 409 with a code if refused). */
  async agreeOsConsent(version: number): Promise<void> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    // Merge pai-c + pai-os: pai-c's Firebase auth headers (no bearerToken field any more).
    Object.assign(headers, await this.authHeaders());
    const res = await fetch(`${API_URL}/v1/os/consent?${params}`, {
      method: 'POST', body: JSON.stringify({ version }), headers, credentials: 'include', cache: 'no-store',
    });
    if (!res.ok) {
      if (res.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event(AUTH_INVALID_EVENT));
      throw new Error(`API ${res.status}: ${await res.text()}`);
    }
  }

  /** PAI OS: start the student's own plan (or get the one they already have). */
  async startOsPlan(route: string, intake: { term: string; year: number },
                    choices: { programme_ref: string; rank: number }[]): Promise<import('./os-self-serve').OsSelfPlan> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/plans/self?${params}`, {
      method: 'POST', body: JSON.stringify({ route, intake, choices }),
    });
  }

  /** PAI OS: swap one programme for another (the screen asks the student first). */
  async swapOsProgramme(planId: number, outRef: string, inRef: string): Promise<import('./os-self-serve').OsSelfPlan> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/plans/${planId}/swap?${params}`, {
      method: 'POST', body: JSON.stringify({ out: outRef, in: inRef }),
    });
  }

  /** PAI OS: drop one programme from the plan while nothing for it has started. */
  async removeOsProgramme(planId: number, ref: string): Promise<import('./os-self-serve').OsSelfPlan> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/plans/${planId}/programmes/${encodeURIComponent(ref)}?${params}`, {
      method: 'DELETE',
    });
  }

  /** PAI OS: ask for a programme that is not on the list; it is researched once and shared. */
  async requestOsProgramme(request: import('./os-self-serve').OsProgrammeRequest): Promise<{ programme_ref: string; created: boolean }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/programmes/requests?${params}`, {
      method: 'POST', body: JSON.stringify(request),
    });
  }

  /** PAI OS: the student's confirmed profile values, each with its source document. */
  async getOsProfile(): Promise<import('./os-documents').OsProfileValue[]> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const body = await this.requestJson<{ values: import('./os-documents').OsProfileValue[] }>(`/v1/os/profile?${params}`);
    return body.values;
  }

  // ---------------------------------------------------------------------------
  // PAI OS statements: the SOP and CV the student co-writes (Slice 5 spec §4)
  // ---------------------------------------------------------------------------

  /** PAI OS: the route's interview questions with the student's answers (open follow-ups first). */
  async getOsInterview(): Promise<import('./os-statements').OsInterview> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/statements/interview?${params}`);
  }

  /** PAI OS: save one answer. `drafting` counts the drafts started again by the last follow-up answer. */
  async saveOsAnswer(questionId: string, answer: string): Promise<{ saved: boolean; drafting: number }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/statements/answers/${encodeURIComponent(questionId)}?${params}`, {
      method: 'PUT', body: JSON.stringify({ answer }),
    });
  }

  /** PAI OS: the student's statements, and each plan programme's statement rules. */
  async getOsStatements(): Promise<import('./os-statements').OsStatements> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const body = await this.requestJson<import('./os-statements').OsStatements>(`/v1/os/statements?${params}`);
    return { statements: body.statements, programmes: body.programmes ?? [] };
  }

  /** PAI OS: start a draft (202). A 409 names the questions still to answer. */
  async draftOsStatement(kind: import('./os-statements').OsStatementKind,
                         programmeRef: string | null = null): Promise<import('./os-statements').OsStatement> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/statements/${kind}/draft?${params}`, {
      method: 'POST', body: JSON.stringify({ programme_ref: programmeRef }),
    });
  }

  /** PAI OS: save the student's edit as a new version; the answer carries its flags. */
  async saveOsStatementText(id: number, text: string): Promise<import('./os-statements').OsStatement> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/statements/${id}/text?${params}`, {
      method: 'PUT', body: JSON.stringify({ text }),
    });
  }

  async approveOsStatement(id: number, version: number): Promise<import('./os-statements').OsApproval & { completed_tasks: number[] }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/statements/${id}/approve?${params}`, {
      method: 'POST', body: JSON.stringify({ version }),
    });
  }

  /** PAI OS: the prompt and limit the student pasted from a programme's page (204, no body). */
  async saveOsStatementRules(programmeRef: string,
                             rules: { prompt?: string | null; limit_words?: number | null; limit_chars?: number | null }): Promise<void> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    // Merge pai-c + pai-os: pai-c's Firebase auth headers (no bearerToken field any more).
    Object.assign(headers, await this.authHeaders());
    const res = await fetch(`${API_URL}/v1/os/statements/rules/${encodeURIComponent(programmeRef)}?${params}`, {
      method: 'PUT', body: JSON.stringify(rules), headers, credentials: 'include', cache: 'no-store',
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  }

  // ---------------------------------------------------------------------------
  // PAI OS application packs (Slice 6a spec §4)
  // ---------------------------------------------------------------------------

  /** PAI OS: one pack per programme in the student's plan (reading also starts any rebuild that is due). */
  async getOsPacks(): Promise<import('./os-packs').OsPacks> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/packs?${params}`);
  }

  async buildOsPack(programmeRef: string): Promise<{ workflow_id: string }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/packs/${encodeURIComponent(programmeRef)}/build?${params}`, { method: 'POST' });
  }

  /** PAI OS: the details no document shows (email, phone, address…). */
  async saveOsPackDetails(fields: Record<string, string | null>): Promise<{ saved: number }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/packs/details?${params}`, { method: 'PUT', body: JSON.stringify({ fields }) });
  }

  async updateOsPackItems(programmeRef: string,
                          change: { tick?: string[]; untick?: string[]; add?: { label: string }[] }): Promise<{ added: string[] }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/packs/${encodeURIComponent(programmeRef)}/items?${params}`, {
      method: 'PUT', body: JSON.stringify(change),
    });
  }

  /**
   * PAI OS: one rendered file, fetched with the same auth headers (no token in a URL), returned as a Blob with the
   * file name the server gave, for the page to save.
   */
  async downloadOsPackFile(programmeRef: string, sha256: string): Promise<{ blob: Blob; filename: string }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const headers: Record<string, string> = {};
    // Merge pai-c + pai-os: pai-c's Firebase auth headers (no bearerToken field any more).
    Object.assign(headers, await this.authHeaders());
    const res = await fetch(`${API_URL}/v1/os/packs/${encodeURIComponent(programmeRef)}/files/${sha256}?${params}`, {
      headers, credentials: 'include', cache: 'no-store',
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
    const m = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '');
    return { blob: await res.blob(), filename: m ? m[1] : `${sha256.slice(0, 12)}.pdf` };
  }

  /** PAI OS: approve the pack version the student is looking at (409 if it changed or is incomplete). */
  async approveOsPack(programmeRef: string, sha256: string): Promise<{ sha256: string; version: number }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/packs/${encodeURIComponent(programmeRef)}/approve?${params}`, {
      method: 'POST', body: JSON.stringify({ sha256 }),
    });
  }

  // ---------------------------------------------------------------------------
  // PAI OS replanning (Slice 7 spec §4)
  // ---------------------------------------------------------------------------

  /** PAI OS: what changed in the student's open plan, and the suggestions waiting for their answer. */
  async getOsChanges(): Promise<import('./os-replan').OsChanges> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/changes?${params}`);
  }

  async acceptOsProposal(id: number): Promise<{ status: string; revision: number | null }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/proposals/${id}/accept?${params}`, { method: 'POST' });
  }

  async declineOsProposal(id: number): Promise<{ status: string }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/proposals/${id}/decline?${params}`, { method: 'POST' });
  }

  /**
   * PAI OS admin calls: the admin token goes in its own header only, never in a URL. A 401 here means a wrong admin
   * token, not an expired session, so it never signs the user out (unlike requestJson).
   */
  private async adminJson<T>(path: string, adminToken: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json', 'X-OS-Admin-Token': adminToken };
    // Merge pai-c + pai-os: pai-c's Firebase auth headers (no bearerToken field any more).
    Object.assign(headers, await this.authHeaders());
    const res = await fetch(`${API_URL}${path}`, { ...options, credentials: 'include', cache: 'no-store', headers });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
    return (await res.json()) as T;
  }

  /** PAI OS admin: support cases. */
  async getOsSupportCases(adminToken: string, status?: 'open' | 'resolved'): Promise<import('./os-replan').OsSupportCase[]> {
    const params = new URLSearchParams({ network: this.requireWorkspace(), ...(status ? { status } : {}) });
    const body = await this.adminJson<{ cases: import('./os-replan').OsSupportCase[] }>(
      `/v1/os/admin/support?${params}`, adminToken);
    return body.cases;
  }

  async resolveOsSupportCase(adminToken: string, id: number, note: string, unpause: boolean): Promise<import('./os-replan').OsSupportCase> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.adminJson(`/v1/os/admin/support/${id}/resolve?${params}`, adminToken, {
      method: 'POST', body: JSON.stringify({ note, unpause }),
    });
  }

  // ---------------------------------------------------------------------------
  // PAI OS visa file (Slice 6b spec §4)
  // ---------------------------------------------------------------------------

  /** PAI OS: the visa file for the chosen (or pre-selected) programme, with the funds the student must show. */
  async getOsVisa(): Promise<import('./os-visa').OsVisa> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/visa?${params}`);
  }

  async saveOsVisaChoice(choice: { programme_ref?: string; reduction?: number }): Promise<{ programme_ref: string | null; reduction: number }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/visa/choice?${params}`, { method: 'PUT', body: JSON.stringify(choice) });
  }

  async buildOsVisa(): Promise<{ workflow_id: string }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/visa/build?${params}`, { method: 'POST' });
  }

  async saveOsVisaDetails(fields: Record<string, string | null>): Promise<{ saved: number }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/visa/details?${params}`, { method: 'PUT', body: JSON.stringify({ fields }) });
  }

  async updateOsVisaItems(change: { tick?: string[]; untick?: string[]; add?: { label: string }[] }): Promise<{ added: string[] }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/visa/items?${params}`, { method: 'PUT', body: JSON.stringify(change) });
  }

  /** PAI OS: one visa file, fetched with the auth headers (no token in a URL). */
  async downloadOsVisaFile(sha256: string): Promise<{ blob: Blob; filename: string }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    const headers: Record<string, string> = {};
    // Merge pai-c + pai-os: pai-c's Firebase auth headers (no bearerToken field any more).
    Object.assign(headers, await this.authHeaders());
    const res = await fetch(`${API_URL}/v1/os/visa/files/${sha256}?${params}`, {
      headers, credentials: 'include', cache: 'no-store',
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
    const m = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '');
    return { blob: await res.blob(), filename: m ? m[1] : `${sha256.slice(0, 12)}.pdf` };
  }

  /** PAI OS: approve the visa file version the student is looking at (409 if it changed, is incomplete or unchosen). */
  async approveOsVisa(sha256: string): Promise<{ sha256: string; version: number }> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    return this.requestJson(`/v1/os/visa/approve?${params}`, { method: 'POST', body: JSON.stringify({ sha256 }) });
  }

  // ---------------------------------------------------------------------------
  // Workspace CRUD (REST endpoints — not event-based)
  // ---------------------------------------------------------------------------

  async getWorkspace(): Promise<Workspace> {
    return this.request<Workspace>(`/v1/workspaces/${this.workspaceId}`);
  }

  async updateWorkspace(updates: { name?: string; settings?: Record<string, unknown>; require_login?: boolean }): Promise<Workspace> {
    return this.request<Workspace>(`/v1/workspaces/${this.workspaceId}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    });
  }

  // ---------------------------------------------------------------------------
  // Nodes — devices running the launcher daemon (connect-a-node)
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // Chat-platform integrations (Slack / Telegram bridges) — workspace access required
  // ---------------------------------------------------------------------------

  async updateMember(agentName: string, updates: { description?: string; role?: string; display_name?: string }): Promise<unknown> {
    return this.request(`/v1/workspaces/${this.workspaceId}/members/${agentName}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    });
  }

  /** Draft a one-line role description for an agent via the router LLM.
   * Returns the suggestion — the caller reviews and saves via updateMember. */
  // ── Custom (user-uploaded) skills ──

  /** Register an already-uploaded file (by file_id) as a custom skill. */
  /** Upload a .md/.zip file and register it as a custom skill in one call. */
  async updateChannel(channelName: string, updates: { title?: string; status?: string; starred?: boolean; masterAgent?: string; orchestrationMode?: string; orchestrationInstruction?: string | null; workflowId?: string | null }): Promise<unknown> {
    // Map camelCase fields → snake_case for the backend.
    const { masterAgent, orchestrationMode, orchestrationInstruction, workflowId, ...rest } = updates;
    const body: Record<string, unknown> = { ...rest };
    if (masterAgent !== undefined) body.master_agent = masterAgent;
    if (orchestrationMode !== undefined) body.orchestration_mode = orchestrationMode;
    if (orchestrationInstruction !== undefined) body.orchestration_instruction = orchestrationInstruction;
    if (workflowId !== undefined) body.workflow_id = workflowId ?? '';
    return this.request(`/v1/workspaces/${this.workspaceId}/channels/${channelName}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  }

  // ---------------------------------------------------------------------------
  // Network discovery
  // ---------------------------------------------------------------------------

  /** Discover agents, channels, and resources in the network. */
  async discover(): Promise<NetworkDiscovery> {
    return this.request<NetworkDiscovery>(`/v1/discover?network=${this.workspaceId}`);
  }

  /** The Roadmap page: which fields the student can get into, computed on read. */
  async getRoadmapPage(): Promise<import('./roadmap').RoadmapPage> {
    return this.request(`/v1/roadmap?network=${this.requireWorkspace()}`);
  }

  async chooseRoute(fieldKey: string): Promise<import('./roadmap').ChosenRoute> {
    return this.request(`/v1/roadmap/choose?network=${this.requireWorkspace()}`,
      { method: 'POST', body: JSON.stringify({ field_key: fieldKey }) });
  }

  /** Tick or untick one step of the chosen route, named by its key. */
  async setRouteStep(key: string, done: boolean): Promise<import('./roadmap').ChosenRoute> {
    return this.request(`/v1/roadmap/steps?network=${this.requireWorkspace()}`,
      { method: 'POST', body: JSON.stringify({ key, done }) });
  }

  async withdrawRoute(): Promise<import('./roadmap').ChosenRoute> {
    return this.request(`/v1/roadmap/withdraw?network=${this.requireWorkspace()}`, { method: 'POST' });
  }

  /** The Mirror state card, computed from the Vault on this read. */
  async getMirror(): Promise<import('./mirror').MirrorCard> {
    const state = await this.request<import('./mirror').MirrorState>(`/v1/counselor/summary?network=${this.requireWorkspace()}`);
    return state.card;
  }

  async getCounselorWorkspace(): Promise<import('./counselor-workspace').LivingPicture> {
    return this.request(`/v1/counselor/workspace?network=${this.requireWorkspace()}`);
  }
  async getFamilyTalk(): Promise<{ready:boolean;message:string;path_id?:string;path?:string;family:{id:string;role:string;wish:string;worry:string;evidence:string}[];evidence:{id:string;quote:string}[]}> {
    return this.request(`/v1/counselor/family-talk?network=${this.requireWorkspace()}`);
  }
  async prepareFamilyTalk(body:{submission_id:string;path_id:string;person_id:string;evidence_ids:string[]}):Promise<{event_id:string;script:string}> {
    return this.request(`/v1/counselor/family-talk?network=${this.requireWorkspace()}`,{method:'POST',body:JSON.stringify(body)});
  }
  async exportCounselorData(): Promise<Record<string, unknown>> {
    return this.request(`/v1/counselor/export?network=${this.requireWorkspace()}`);
  }
  async deleteMyAccount(): Promise<void> {
    try {
      await this.request('/v1/account', {method:'DELETE'});
    } catch (error) {
      if (error instanceof Error && error.message.includes('AUTH_RECENT_SIGN_IN_REQUIRED')) throw new RecentSignInRequired();
      throw error;
    }
  }

  async getCounselorHealth(): Promise<import('./counselor-workspace').CounselorHealth> {
    return this.request(`/v1/counselor/health?network=${this.requireWorkspace()}`);
  }
  // ---- The student's Vault (/v1/vault): one view, the catalog and the student's own edits.
  // Writes need the signed-in owner; a refused write's message is for the student (see lib/vault.ts vaultError).
  async getVault():Promise<import('./vault').VaultView> {
    return this.request(`/v1/vault?network=${this.requireWorkspace()}`);
  }
  async getVaultCatalog():Promise<import('./vault').VaultCatalog> {
    return this.request(`/v1/vault/catalog?network=${this.requireWorkspace()}`);
  }
  async addVaultEntry(type:string,value:unknown):Promise<import('./vault').VaultWriteResult> {
    return this.request(`/v1/vault/entries?network=${this.requireWorkspace()}`,{method:'POST',body:JSON.stringify({type,value})});
  }
  async editVaultEntry(kind:string,id:string,value:unknown):Promise<import('./vault').VaultWriteResult> {
    return this.request(`/v1/vault/entries/${encodeURIComponent(kind)}/${encodeURIComponent(id)}?network=${this.requireWorkspace()}`,{method:'PATCH',body:JSON.stringify({value})});
  }
  async confirmVaultEntry(kind:string,id:string):Promise<import('./vault').VaultWriteResult> {
    return this.request(`/v1/vault/entries/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/confirm?network=${this.requireWorkspace()}`,{method:'POST'});
  }
  async removeVaultEntry(kind:string,id:string):Promise<import('./vault').VaultWriteResult> {
    return this.request(`/v1/vault/entries/${encodeURIComponent(kind)}/${encodeURIComponent(id)}?network=${this.requireWorkspace()}`,{method:'DELETE'});
  }
  async vaultHistory(kind:string,id:string):Promise<{kind:string;type:string;id:string;history:Record<string,unknown>[]}> {
    return this.request(`/v1/vault/entries/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/history?network=${this.requireWorkspace()}`);
  }
  async resolveVaultConflict(issueId:string,answer:import('./vault').VaultAnswer,value?:unknown):Promise<Record<string,unknown>> {
    return this.request(`/v1/vault/conflicts/${encodeURIComponent(issueId)}/resolve?network=${this.requireWorkspace()}`,
      {method:'POST',body:JSON.stringify({answer,...(value!==undefined?{value}:{})})});
  }
  async getVaultDocumentEntries(fileId:string):Promise<{file_id:string;entries:import('./vault').VaultEntry[]}> {
    return this.request(`/v1/vault/documents/${encodeURIComponent(fileId)}/entries?network=${this.requireWorkspace()}`);
  }
  async answerFactCard(id:string,body:Record<string,unknown>):Promise<unknown> {
    return this.request(`/v1/counselor/fact-cards/${encodeURIComponent(id)}?network=${this.requireWorkspace()}`,{method:'POST',body:JSON.stringify(body)});
  }
  async getPath(id:string):Promise<import('./counselor-workspace').PathResult> {
    return this.request(`/v1/counselor/paths/${encodeURIComponent(id)}?network=${this.requireWorkspace()}`);
  }
  async getPrograms(id:string):Promise<import('./counselor-workspace').Programs> {
    return this.request(`/v1/counselor/paths/${encodeURIComponent(id)}/programs?network=${this.requireWorkspace()}`);
  }
  async searchPrograms(id:string):Promise<unknown> {
    return this.request(`/v1/counselor/paths/${encodeURIComponent(id)}/programs?network=${this.requireWorkspace()}`,{method:'POST',body:JSON.stringify({explore_places:true})});
  }
  async acceptPathActivity(id:string):Promise<{status:string;available_at:string}> {
    return this.request(`/v1/counselor/paths/${encodeURIComponent(id)}/try-it?network=${this.requireWorkspace()}`,{method:'POST',body:JSON.stringify({accepted:true})});
  }
  async getPossibilities(): Promise<import('./possibilities').Possibility[]> {
    const result = await this.request<{ possibilities: import('./possibilities').Possibility[] }>(
      `/v1/counselor/possibilities?network=${this.requireWorkspace()}`);
    return result.possibilities;
  }

  async changePossibility(id: string, action: 'explore' | 'save' | 'dismiss'): Promise<import('./possibilities').Possibility> {
    return this.request(`/v1/counselor/possibilities/${encodeURIComponent(id)}/${action}?network=${this.requireWorkspace()}`,
      { method: 'POST' });
  }

  /** A path the student puts in themselves; PAI then checks it against them. */
  async addOwnPath(title: string, why = ''): Promise<import('./possibilities').Possibility> {
    return this.request(`/v1/counselor/possibilities?network=${this.requireWorkspace()}`,
      { method: 'POST', body: JSON.stringify({ title, why }) });
  }

  /** The latest path analysis PAI ran on its own: whether it is done and how it ended. */
  async getPathAnalysis(): Promise<import('./possibilities').PathAnalysisStatus> {
    return this.request(`/v1/counselor/possibilities/analysis?network=${this.requireWorkspace()}`);
  }

  async getStudentRequests(): Promise<import('./student-requests').StudentRequest[]> {
    const response = await this.request<{ requests: import('./student-requests').StudentRequest[] }>(
      `/v1/student-requests?network=${this.requireWorkspace()}`);
    return response.requests;
  }

  // ---------------------------------------------------------------------------
  // First-run onboarding
  // ---------------------------------------------------------------------------

  /** Whether this account still owes the first-run form, plus any prefill. */
  async getOnboarding(): Promise<import('./onboarding').OnboardingState> {
    return this.request<import('./onboarding').OnboardingState>(
      `/v1/vault/onboarding?network=${this.requireWorkspace()}`,
    );
  }

  /** Submit the answers. They become canonical Vault facts, not a form row. */
  async submitOnboarding(
    answers: import('./onboarding').OnboardingAnswers,
  ): Promise<import('./onboarding').OnboardingResult> {
    return this.request<import('./onboarding').OnboardingResult>(
      `/v1/vault/onboarding?network=${this.requireWorkspace()}`,
      { method: 'POST', body: JSON.stringify({ answers }) },
    );
  }

  /**
   * Where an uploaded PDF/DOCX is up to. `document_stage` is the person-facing
   * stage (reading -> understanding -> done); it is server-owned, so a chat
   * reopened mid-processing shows the real state instead of an idle file.
   */
  async getDocumentStage(fileId: string): Promise<DocumentStage> {
    const info = await this.request<{ document_stage?: DocumentStage }>(
      `/v1/files/${encodeURIComponent(fileId)}/info`,
    );
    return info?.document_stage ?? 'unsupported';
  }

  // ---------------------------------------------------------------------------
  // Channels (sessions) — via ONM events
  // ---------------------------------------------------------------------------

  /** Create a new channel (thread) by emitting a network.channel.create event. */
  async createChannel(opts: {
    title?: string;
    master?: string;
    participants?: string[];
  } = {}): Promise<WorkspaceSession> {
    const event = await this.sendEvent({
      type: 'network.channel.create',
      target: 'core',
      payload: {
        ...(opts.title && { title: opts.title }),
        ...(opts.master && { master: opts.master }),
        ...(opts.participants && { participants: opts.participants }),
      },
    });

    // Build a WorkspaceSession from the event response
    const channelName = (event.metadata?.channel_name as string) || '';
    return {
      sessionId: channelName,
      workspaceId: this.workspaceId,
      createdBy: 'human:user',
      title: opts.title
        || (opts.participants && opts.participants.length
          ? `New Thread with ${opts.participants[0]}${opts.participants.length > 1 ? ` +${opts.participants.length - 1}` : ''}`
          : 'New Thread'),
      status: 'active',
      starred: false,
      participants: opts.participants || [],
      master: opts.master || null,
      orchestrationMode: 'dynamic',
      orchestrationInstruction: null,
      workflowId: null,
      createdAt: new Date(event.timestamp).toISOString(),
      lastEventAt: null,
    };
  }

  /** Add an agent to an existing channel. */
  async addChannelParticipant(channelName: string, agentName: string): Promise<void> {
    await this.sendEvent({
      type: 'network.channel.join',
      target: `channel/${channelName}`,
      payload: { channel: channelName, agent_name: agentName },
    });
  }

  /** Remove an agent from an existing channel. */
  async removeChannelParticipant(channelName: string, agentName: string): Promise<void> {
    await this.sendEvent({
      type: 'network.channel.leave',
      target: `channel/${channelName}`,
      payload: { channel: channelName, agent_name: agentName },
    });
  }

  // ---------------------------------------------------------------------------
  // Messages — via ONM events
  // ---------------------------------------------------------------------------

  /** Send a chat message by emitting a workspace.message.posted event. */
  async sendMessage(
    channelName: string,
    content: string,
    senderName = 'user',
    mentions?: string[],
    attachments?: { fileId: string; filename: string; contentType: string; url: string }[],
    senderId?: string,
  ): Promise<ONMEvent> {
    return this.sendEvent({
      type: 'workspace.message.posted',
      target: `channel/${channelName}`,
      payload: {
        content,
        sender_type: 'human',
        ...(senderId ? { sender_id: senderId } : {}),
        sender_name: senderName,
        ...(mentions && mentions.length > 0 ? { mentions } : {}),
        ...(attachments && attachments.length > 0 ? { attachments } : {}),
      },
      visibility: 'channel',
    });
  }

  /** The server authenticates this WebRTC offer with its permanent OpenAI key. */
  async createCounselorVoiceSession(conversation: string, sdp: string): Promise<{ session_id: string; sdp: string }> {
    return this.request<{ session_id: string; sdp: string }>('/v1/counselor/voice/session', {
      method: 'POST',
      body: JSON.stringify({ network: this.requireWorkspace(), conversation, sdp }),
    });
  }

  /** Post a spoken turn to the same Counselor event pipeline used by text. */
  async sendCounselorVoiceTurn(conversation: string, content: string, delegationId: string, senderName: string, senderId: string, voiceSessionId?: string): Promise<ONMEvent> {
    return this.sendEvent({
      type: 'workspace.message.posted',
      target: `channel/${conversation}`,
      payload: { content, sender_type: 'human', sender_id: senderId, sender_name: senderName },
      metadata: { target_agents: ['pai'], voice_delegation_id: delegationId,
        ...(voiceSessionId ? { voice_session_id: voiceSessionId } : {}) },
      visibility: 'channel',
    });
  }

  /**
   * Send a direct message (DM) to one agent or human.
   *
   * DMs are events with visibility 'direct' targeted at the recipient's
   * address (openagents:<name> / human:<id>) instead of a channel. The
   * explicit target_agents metadata is REQUIRED for agent recipients: the
   * backend router only computes routing for channel targets, and adapters
   * treat an un-targeted human message as broadcast — without the list every
   * agent in the workspace would pick the DM up. The human side of web DMs is
   * canonicalized to `human:user` so all of a user's DMs with a counterpart
   * group into one conversation (real name/id still travel in the payload).
   */
  async sendDirectMessage(
    counterpart: string,
    content: string,
    senderName = 'user',
    senderId?: string,
  ): Promise<ONMEvent> {
    const isAgent = counterpart.startsWith('openagents:');
    return this.sendEvent({
      type: 'workspace.message.posted',
      target: counterpart,
      payload: {
        content,
        sender_type: 'human',
        ...(senderId ? { sender_id: senderId } : {}),
        sender_name: senderName,
      },
      metadata: {
        target_agents: isAgent
          ? [counterpart.replace(/^openagents:/, '')]
          : ['__no_response__'],
      },
      visibility: 'direct',
    });
  }

  /**
   * Poll messages for a channel (session) via the event API.
   * Returns WorkspaceMessage[] for component compatibility.
   */
  async pollMessages(channelName: string, after?: string): Promise<MessagePollResponse> {
    const result = await this.pollEvents({
      channel: channelName,
      type: 'workspace.message',
      after,
      limit: 200,
    });

    return {
      messages: result.events.map(eventToMessage),
      hasMore: result.has_more,
    };
  }

  // ---------------------------------------------------------------------------
  // Composing signal — notify backend that a user is typing
  // ---------------------------------------------------------------------------

  async sendComposing(channelName: string): Promise<void> {
    try {
      await this.request<unknown>('/v1/composing', {
        method: 'POST',
        body: JSON.stringify({ network: this.workspaceId, channel: channelName }),
      });
    } catch {
      // Fire-and-forget
    }
  }

  // ---------------------------------------------------------------------------
  // Agent control — mode changes etc.
  // ---------------------------------------------------------------------------

  /** Send a control event to an agent (e.g. mode change). */
  async sendAgentControl(
    agentName: string,
    action: string,
    params: Record<string, unknown> = {},
  ): Promise<ONMEvent> {
    return this.sendEvent({
      type: 'workspace.agent.control',
      target: `openagents:${agentName}`,
      payload: { action, ...params },
      visibility: 'direct',
    });
  }

  // ---------------------------------------------------------------------------
  // Files
  // ---------------------------------------------------------------------------

  /**
   * Upload a file to workspace shared storage.
   *
   * XHR rather than fetch for one reason: `upload.onprogress`. A fetch request
   * body is opaque once it's handed over, so there is no way to tell a 40MB
   * upload apart from a stalled one — and the grid draws a progress bar over
   * the file while it goes up.
   */
  uploadFile(
    file: File,
    channelName?: string,
    options?: {
      /** Fraction uploaded, 0–1. Never fires if the browser can't measure it. */
      onProgress?: (fraction: number) => void;
      signal?: AbortSignal;
    },
  ): Promise<WorkspaceFile> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('network', this.workspaceId);
    if (channelName) formData.append('channel_name', channelName);

    return this.authHeaders().then((headers) => new Promise<WorkspaceFile>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_URL}/v1/files`);
      for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);

      if (options?.onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable && e.total > 0) options.onProgress!(e.loaded / e.total);
        };
      }

      xhr.onload = () => {
        if (xhr.status < 200 || xhr.status >= 300) {
          reject(new Error(`Upload failed: ${xhr.responseText || xhr.statusText}`));
          return;
        }
        try {
          resolve(mapFileResponse(JSON.parse(xhr.responseText).data));
        } catch {
          reject(new Error('Upload failed: malformed response'));
        }
      };
      xhr.onerror = () => reject(new Error('Upload failed: network error'));
      xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'));

      if (options?.signal) {
        if (options.signal.aborted) {
          reject(new DOMException('Upload cancelled', 'AbortError'));
          return;
        }
        options.signal.addEventListener('abort', () => xhr.abort(), { once: true });
      }

      xhr.send(formData);
    }));
  }

  /**
   * List every file in the workspace.
   *
   * The endpoint pages at 50 by default and caps at 200, but the Files view
   * derives the whole folder tree from this list — a partial page silently
   * drops folders and makes their counts shrink as new files arrive, so we
   * walk the pages until we have them all.
   */
  async listFiles(): Promise<{ files: WorkspaceFile[]; total: number }> {
    const PAGE_SIZE = 200; // the endpoint's hard ceiling
    const MAX_PAGES = 25;  // 5k files: a backstop, not an expected limit
    const files: WorkspaceFile[] = [];
    let total = 0;

    for (let page = 0; page < MAX_PAGES; page++) {
      const raw = await this.request<{ files: Record<string, unknown>[]; total: number }>(
        `/v1/files?network=${this.workspaceId}&limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`
      );
      total = raw.total;
      files.push(...raw.files.map(mapFileResponse));
      if (raw.files.length < PAGE_SIZE || files.length >= total) break;
    }

    return { files, total };
  }

  /** Get the download URL for a file. */
  getFileUrl(fileId: string): string {
    const qs = this.urlCredential(new URLSearchParams()).toString();
    return `${API_URL}/v1/files/${fileId}${qs ? `?${qs}` : ''}`;
  }

  /** Delete a file. */
  async deleteFile(fileId: string): Promise<void> {
    await this.request<unknown>(`/v1/files/${fileId}`, { method: 'DELETE' });
  }

  /**
   * Folders are a path prefix on `filename`, not rows of their own, so these
   * rewrite or soft-delete every record under the prefix server-side.
   */
  async createFolder(path: string): Promise<void> {
    await this.request<unknown>('/v1/files/folders', {
      method: 'POST',
      body: JSON.stringify({ network: this.workspaceId, path }),
    });
  }

  async renameFolder(path: string, newPath: string): Promise<void> {
    await this.request<unknown>('/v1/files/folders', {
      method: 'PATCH',
      body: JSON.stringify({ network: this.workspaceId, path, new_path: newPath }),
    });
  }

  async deleteFolder(path: string): Promise<void> {
    const params = new URLSearchParams({ network: this.workspaceId, path });
    await this.request<unknown>(`/v1/files/folders?${params}`, { method: 'DELETE' });
  }

  // ---------------------------------------------------------------------------
  // Trash
  //
  // Deleting is soft: files and folders land here first and can be put back.
  // The unit is the delete action, not the file — a deleted folder is one entry
  // holding its files — so restore and purge take `trashId`s, never file ids.
  // ---------------------------------------------------------------------------

  /**
   * Move files and/or folders to the trash.
   *
   * Preferred over `deleteFile`/`deleteFolder`: those routes predate the trash
   * and record no timestamp or grouping, so what they delete comes back as one
   * loose row per file, undated and unrestorable as a unit.
   */
  async moveToTrash(target: { fileIds?: string[]; paths?: string[] }): Promise<void> {
    await this.request<unknown>('/v1/files/trash', {
      method: 'POST',
      body: JSON.stringify({
        network: this.workspaceId,
        file_ids: target.fileIds ?? [],
        paths: target.paths ?? [],
      }),
    });
  }

  /** What's in the trash, newest first. Paged for the same reason as listFiles. */
  async listTrash(): Promise<{
    entries: TrashEntry[];
    total: number;
    fileTotal: number;
    sizeTotal: number;
  }> {
    const PAGE_SIZE = 500; // the endpoint's hard ceiling
    const MAX_PAGES = 10;
    const entries: TrashEntry[] = [];
    let total = 0;
    let fileTotal = 0;
    let sizeTotal = 0;

    for (let page = 0; page < MAX_PAGES; page++) {
      const raw = await this.request<{
        entries: Record<string, unknown>[];
        total: number;
        file_total: number;
        size_total: number;
      }>(
        `/v1/files/trash?network=${this.workspaceId}&limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`
      );
      total = raw.total;
      fileTotal = raw.file_total;
      sizeTotal = raw.size_total;
      entries.push(...raw.entries.map(mapTrashEntry));
      if (raw.entries.length < PAGE_SIZE || entries.length >= total) break;
    }

    return { entries, total, fileTotal, sizeTotal };
  }

  /**
   * Put trash entries back where they were.
   *
   * A name taken in the meantime doesn't fail the restore — the file lands
   * beside its replacement as "report (2).pdf" — so `renamedCount` is what the
   * caller needs to say so rather than claiming an exact restore.
   */
  async restoreFromTrash(trashIds: string[]): Promise<{ restoredCount: number; renamedCount: number }> {
    const data = await this.request<{
      entries: { renamed_count?: number }[];
      restored_count: number;
    }>('/v1/files/trash/restore', {
      method: 'POST',
      body: JSON.stringify({ network: this.workspaceId, trash_ids: trashIds }),
    });
    return {
      restoredCount: data.restored_count ?? 0,
      renamedCount: (data.entries ?? []).reduce((n, e) => n + (e.renamed_count ?? 0), 0),
    };
  }

  /** Destroy trash entries — records and stored bytes. `all` is Empty Trash. */
  async purgeTrash(target: { trashIds?: string[]; all?: boolean }): Promise<void> {
    await this.request<unknown>('/v1/files/trash/purge', {
      method: 'POST',
      body: JSON.stringify({
        network: this.workspaceId,
        trash_ids: target.trashIds ?? [],
        all: target.all ?? false,
      }),
    });
  }

  // ---------------------------------------------------------------------------
  // Knowledge Base
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // Browser
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // Agent management (stubs — not yet event-native)
  // ---------------------------------------------------------------------------

  /** Fetch the catalog of supported agent client types. */

  // ---------------------------------------------------------------------------
  // Low-level ONM event API
  // ---------------------------------------------------------------------------

  /** Send an event through the mod pipeline. */
  /**
   * Post an event. The server derives WHO sent it from the caller's
   * credentials — there is no `source` to supply, and one sent anyway would be
   * discarded. See workspace/backend/app/event_identity.py.
   */
  async sendEvent(event: {
    type: string;
    target: string;
    payload?: Record<string, unknown>;
    metadata?: Record<string, unknown>;
    visibility?: string;
  }): Promise<ONMEvent> {
    const network = this.requireWorkspace();
    return this.request<ONMEvent>('/v1/events', {
      method: 'POST',
      body: JSON.stringify({ ...event, network }),
    });
  }

  /** Poll events from the network. */
  async pollEvents(opts: {
    after?: string;
    before?: string;
    target?: string;
    channel?: string;
    type?: string;
    search?: string;
    sort?: 'asc' | 'desc';
    limit?: number;
    excludeMessageTypes?: string[];
  } = {}): Promise<EventPollResponse> {
    const params = new URLSearchParams({ network: this.requireWorkspace() });
    if (opts.after) params.set('after', opts.after);
    if (opts.before) params.set('before', opts.before);
    if (opts.target) params.set('target', opts.target);
    if (opts.channel) params.set('channel', opts.channel);
    if (opts.type) params.set('type', opts.type);
    if (opts.search) params.set('search', opts.search);
    if (opts.excludeMessageTypes?.length) params.set('exclude_message_types', opts.excludeMessageTypes.join(','));
    if (opts.sort) params.set('sort', opts.sort);
    if (opts.limit) params.set('limit', String(opts.limit));
    return this.request<EventPollResponse>(`/v1/events?${params}`);
  }

  /**
   * Load message history for a channel (most recent first).
   * Used for initial load and infinite scroll (loading older messages).
   *
   * Intermediate agent output (thinking/status/todos) is excluded so the
   * `limit` window only counts real chat messages — a busy agent can emit
   * hundreds of status events, which would otherwise push the user's own
   * message out of the first page on refresh. Current-step events are
   * re-fetched by the forward poll (which starts after the newest chat
   * message and applies no exclusion).
   */
  async loadMessageHistory(
    channelName: string,
    options?: { before?: string; limit?: number },
  ): Promise<EventPollResponse> {
    return this.pollEvents({
      channel: channelName,
      type: 'workspace.message',
      before: options?.before,
      sort: 'desc',
      limit: options?.limit ?? 50,
      excludeMessageTypes: ['thinking', 'status', 'todos'],
    });
  }

  // ---------------------------------------------------------------------------
  // Agent DM conversations
  // ---------------------------------------------------------------------------

  /** List active agent-to-agent DM conversations. */
  async listConversations(agentFilter?: string): Promise<DMConversation[]> {
    const params = new URLSearchParams({ network: this.workspaceId });
    if (agentFilter) params.set('agent', agentFilter);
    const result = await this.request<{ conversations: Array<{
      agents: [string, string];
      last_message: { content: string; sender: string; timestamp: number };
      message_count: number;
    }> }>(`/v1/events/conversations?${params}`);
    return result.conversations.map((c) => ({
      agents: c.agents,
      lastMessage: c.last_message,
      messageCount: c.message_count,
    }));
  }

  /** Poll messages for a DM conversation between two agents. */
  async pollConversation(
    agentA: string,
    agentB: string,
    opts?: { after?: string; before?: string; sort?: 'asc' | 'desc'; limit?: number; excludeMessageTypes?: string[] },
  ): Promise<EventPollResponse> {
    const params = new URLSearchParams({ network: this.workspaceId });
    params.set('conversation', `${agentA},${agentB}`);
    params.set('type', 'workspace.message');
    if (opts?.after) params.set('after', opts.after);
    if (opts?.before) params.set('before', opts.before);
    if (opts?.sort) params.set('sort', opts.sort);
    if (opts?.limit) params.set('limit', String(opts.limit));
    if (opts?.excludeMessageTypes?.length) params.set('exclude_message_types', opts.excludeMessageTypes.join(','));
    return this.request<EventPollResponse>(`/v1/events?${params}`);
  }

  // ---------------------------------------------------------------------------
  // Bulk thread previews
  // ---------------------------------------------------------------------------

  /** Fetch the latest message event per channel in a single request. */
  async latestPerChannel(): Promise<{ channels: Record<string, ONMEvent> }> {
    const params = new URLSearchParams({ network: this.workspaceId });
    return this.request<{ channels: Record<string, ONMEvent> }>(`/v1/events/latest-per-channel?${params}`);
  }

  // ---------------------------------------------------------------------------
  // Todos / Tasks
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // Kanban tasks (workspace-wide board)
  // ---------------------------------------------------------------------------

  private mapRunInfo(r: Record<string, unknown>): TaskRunInfo {
    return {
      status: (r.status || 'running') as TaskRunInfo['status'],
      stepIndex: (r.step_index as number) ?? -1,
      stepCount: (r.step_count as number) ?? 0,
      stepName: (r.step_name as string) || null,
      stepAssignee: (r.step_assignee as string) || null,
      stepAssigneeKind: (r.step_assignee_kind as TaskRunInfo['stepAssigneeKind']) || null,
      iterations: (r.iterations as number) ?? 0,
      maxIterations: (r.max_iterations as number) ?? 5,
    };
  }

  private mapTask(t: Record<string, unknown>): KanbanTask {
    return {
      id: t.id as string,
      title: (t.title || '') as string,
      description: (t.description || '') as string,
      status: (t.status || 'backlog') as KanbanTask['status'],
      assignee: (t.assignee || null) as string | null,
      workflowId: (t.workflow_id || null) as string | null,
      knowledgeIds: (t.knowledge_ids || []) as string[],
      fileIds: (t.file_ids || []) as string[],
      createdBy: (t.created_by || '') as string,
      channelName: (t.channel_name || null) as string | null,
      position: (t.position || 0) as number,
      run: t.run ? this.mapRunInfo(t.run as Record<string, unknown>) : null,
      lastMessage: (t.last_message || null) as string | null,
      createdAt: (t.created_at || null) as string | null,
      updatedAt: (t.updated_at || null) as string | null,
    };
  }

  async listTasks(): Promise<{ tasks: KanbanTask[] }> {
    const params = new URLSearchParams({ network: this.workspaceId });
    const raw = await this.request<{ tasks: Record<string, unknown>[] }>(`/v1/tasks?${params}`);
    return { tasks: (raw.tasks || []).map((t) => this.mapTask(t)) };
  }

  async createTask(input: {
    title: string;
    description?: string;
    status?: KanbanTask['status'];
    assignee?: string | null;
    workflowId?: string | null;
    knowledgeIds?: string[];
    fileIds?: string[];
  }): Promise<KanbanTask> {
    const raw = await this.request<Record<string, unknown>>(`/v1/tasks`, {
      method: 'POST',
      body: JSON.stringify({
        network: this.workspaceId,
          title: input.title,
        description: input.description ?? '',
        status: input.status ?? 'backlog',
        ...(input.assignee ? { assignee: input.assignee } : {}),
        ...(input.workflowId ? { workflow_id: input.workflowId } : {}),
        ...(input.knowledgeIds?.length ? { knowledge_ids: input.knowledgeIds } : {}),
        ...(input.fileIds?.length ? { file_ids: input.fileIds } : {}),
      }),
    });
    return this.mapTask(raw);
  }

  async updateTask(id: string, updates: {
    title?: string;
    description?: string;
    status?: KanbanTask['status'];
    position?: number;
    assignee?: string | null;
    workflowId?: string | null;
    knowledgeIds?: string[];
    fileIds?: string[];
  }): Promise<KanbanTask> {
    const { workflowId, knowledgeIds, fileIds, ...rest } = updates;
    const raw = await this.request<Record<string, unknown>>(`/v1/tasks/${id}`, {
      method: 'PATCH',
      // Send assignee/workflow_id as "" (not null) to clear them — the backend
      // treats empty string as "clear" and JSON.stringify drops `undefined`.
      body: JSON.stringify({
        network: this.workspaceId,
        ...rest,
        ...(rest.assignee === null ? { assignee: '' } : {}),
        ...(workflowId !== undefined ? { workflow_id: workflowId ?? '' } : {}),
        ...(knowledgeIds !== undefined ? { knowledge_ids: knowledgeIds } : {}),
        ...(fileIds !== undefined ? { file_ids: fileIds } : {}),
      }),
    });
    return this.mapTask(raw);
  }

  /** Run a task. Omit `agent` to run the task's stored assignee. */
  async assignTask(id: string, agent?: string): Promise<KanbanTask> {
    const raw = await this.request<Record<string, unknown>>(`/v1/tasks/${id}/assign`, {
      method: 'POST',
      body: JSON.stringify({
        network: this.workspaceId,
          ...(agent ? { agent } : {}),
      }),
    });
    return this.mapTask(raw);
  }

  async deleteTask(id: string): Promise<void> {
    const params = new URLSearchParams({ network: this.workspaceId });
    await this.request(`/v1/tasks/${id}?${params}`, { method: 'DELETE' });
  }

  // ---------------------------------------------------------------------------
  // Workflows (collaboration templates)
  // ---------------------------------------------------------------------------

  private mapWorkflow(w: Record<string, unknown>): Workflow {
    return {
      id: w.id as string,
      name: (w.name || '') as string,
      description: (w.description || '') as string,
      steps: ((w.steps as WorkflowStep[]) || []),
      maxIterations: (w.max_iterations as number) ?? 5,
      createdBy: (w.created_by || '') as string,
      createdAt: (w.created_at || null) as string | null,
      updatedAt: (w.updated_at || null) as string | null,
    };
  }

  async listWorkflows(): Promise<{ workflows: Workflow[] }> {
    const params = new URLSearchParams({ network: this.workspaceId });
    const raw = await this.request<{ workflows: Record<string, unknown>[] }>(`/v1/workflows?${params}`);
    return { workflows: (raw.workflows || []).map((w) => this.mapWorkflow(w)) };
  }

  async createWorkflow(input: { name: string; description?: string; steps: WorkflowStep[]; maxIterations?: number }): Promise<Workflow> {
    const raw = await this.request<Record<string, unknown>>(`/v1/workflows`, {
      method: 'POST',
      body: JSON.stringify({
        network: this.workspaceId,
          name: input.name,
        description: input.description ?? '',
        steps: input.steps,
        max_iterations: input.maxIterations ?? 5,
      }),
    });
    return this.mapWorkflow(raw);
  }

  async updateWorkflow(id: string, updates: { name?: string; description?: string; steps?: WorkflowStep[]; maxIterations?: number }): Promise<Workflow> {
    const raw = await this.request<Record<string, unknown>>(`/v1/workflows/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        network: this.workspaceId,
        ...(updates.name !== undefined ? { name: updates.name } : {}),
        ...(updates.description !== undefined ? { description: updates.description } : {}),
        ...(updates.steps !== undefined ? { steps: updates.steps } : {}),
        ...(updates.maxIterations !== undefined ? { max_iterations: updates.maxIterations } : {}),
      }),
    });
    return this.mapWorkflow(raw);
  }

  async deleteWorkflow(id: string): Promise<void> {
    const params = new URLSearchParams({ network: this.workspaceId });
    await this.request(`/v1/workflows/${id}?${params}`, { method: 'DELETE' });
  }

  async cancelQueuedMessage(channelName: string, queueId: string): Promise<void> {
    await this.sendEvent({
      type: 'workspace.message.posted',
      target: `channel/${channelName}`,
      payload: {
        content: `__queue_cancel:${queueId}`,
        message_type: 'queue_cancel',
      },
    });
  }

  // ---------------------------------------------------------------------------
  // Notifications / Inbox
  // ---------------------------------------------------------------------------

  async listNotifications(opts?: { status?: string; isRead?: boolean; limit?: number; offset?: number }): Promise<{ notifications: NotificationItem[]; unreadCount: number }> {
    const params = new URLSearchParams({ network: this.workspaceId });
    if (opts?.status) params.set('status', opts.status);
    if (opts?.isRead !== undefined) params.set('is_read', String(opts.isRead));
    if (opts?.limit) params.set('limit', String(opts.limit));
      if (opts?.offset) params.set('offset', String(opts.offset));
    const raw = await this.request<{ notifications: Record<string, unknown>[]; unread_count: number }>(`/v1/notifications?${params}`);
    return {
      notifications: (raw.notifications || []).map((n): NotificationItem => ({
        id: n.id as string,
        title: n.title as string,
        message: n.message as string,
        priority: (n.priority || 'normal') as NotificationItem['priority'],
        isRead: !!(n.is_read),
        createdBy: (n.created_by || '') as string,
        channelName: (n.channel_name ?? null) as string | null,
        threadId: (n.thread_id ?? null) as string | null,
        linkUrl: (n.link_url ?? null) as string | null,
        status: (n.status || 'active') as string,
        createdAt: (n.created_at || null) as string | null,
        readAt: (n.read_at || null) as string | null,
      })),
      unreadCount: raw.unread_count || 0,
    };
  }

  async markNotificationRead(notificationId: string): Promise<void> {
    await this.request<unknown>(`/v1/notifications/${notificationId}/read`, { method: 'PATCH' });
  }

  /** Map a raw ExecutionRun payload (GET /v1/operator/runs, or the SSE
   * "workspace.operator.run_updated" event payload — same shape, see
   * operator.serialize_run) into the frontend's OperatorRun. Public so the
   * realtime hook (use-operator-status.ts) can reuse it for SSE payloads,
   * not just this class's own polling call below. */
  mapOperatorRun(r: Record<string, unknown>): OperatorRun {
    return {
      id: r.id as string,
      objective: r.objective as string,
      taskType: (r.task_type ?? null) as string | null,
      status: r.status as OperatorRun['status'],
      currentStep: (r.current_step ?? null) as string | null,
      plan: (r.plan || []) as OperatorRun['plan'],
      completedSteps: (r.completed_steps || []) as string[],
      toolCalls: (r.tool_calls || []) as OperatorRun['toolCalls'],
      missing: (r.missing || []) as string[],
      approvalRequiredFor: (r.approval_required_for ?? null) as string | null,
      pendingAction: (r.pending_action ?? null) as Record<string, unknown> | null,
      error: (r.error ?? null) as string | null,
      result: (r.result ?? null) as Record<string, unknown> | null,
      verification: (r.verification ?? null) as Record<string, unknown> | null,
      resultType: (r.result_type ?? null) as string | null,
      resultArtifactId: (r.result_artifact_id ?? null) as string | null,
      createdAt: (r.created_at || null) as string | null,
      updatedAt: (r.updated_at || null) as string | null,
      completedAt: (r.completed_at ?? null) as string | null,
    };
  }

  /** PAI Operator's runs — read-only, for the "PAI is working…" indicator.
   * Never invoked from the frontend to start work: only PAI Counselor's
   * operator.delegate tool creates a run. */
  async listOperatorRuns(opts?: { status?: 'active' | OperatorRun['status']; limit?: number }): Promise<{ runs: OperatorRun[] }> {
    const params = new URLSearchParams({ network: this.workspaceId });
    if (opts?.status) params.set('status', opts.status);
    if (opts?.limit) params.set('limit', String(opts.limit));
    const raw = await this.request<{ runs: Record<string, unknown>[] }>(`/v1/operator/runs?${params}`);
    return { runs: (raw.runs || []).map((r) => this.mapOperatorRun(r)) };
  }

  async markAllNotificationsRead(): Promise<void> {
    await this.request<unknown>(`/v1/notifications/read-all?network=${this.workspaceId}`, { method: 'PATCH' });
  }

  async dismissNotification(notificationId: string): Promise<void> {
    await this.request<unknown>(`/v1/notifications/${notificationId}`, { method: 'DELETE' });
  }

  // ---------------------------------------------------------------------------
  // Shares (conversation snapshots)
  // ---------------------------------------------------------------------------

  async createShare(channelName: string, createdBy?: string): Promise<ShareSummary> {
    const raw = await this.request<Record<string, unknown>>('/v1/shares', {
      method: 'POST',
      body: JSON.stringify({
        network: this.workspaceId,
        channel: channelName,
        created_by: createdBy || 'human:user',
      }),
    });
    return {
      id: raw.id as string,
      workspaceId: (raw.workspace_id || '') as string,
      channelName: (raw.channel_name || '') as string,
      title: (raw.title || null) as string | null,
      shareToken: raw.share_token as string,
      messageCount: (raw.message_count || 0) as number,
      status: (raw.status || 'active') as string,
      createdAt: (raw.created_at || null) as string | null,
    };
  }

  /** The student's active share links, newest first. */
  async listShares(): Promise<ShareSummary[]> {
    const raw = await this.request<Record<string, unknown>[]>(`/v1/shares?network=${this.workspaceId}`);
    return (raw || []).map((row) => ({
      id: row.id as string,
      workspaceId: (row.workspace_id || '') as string,
      channelName: (row.channel_name || '') as string,
      title: (row.title || null) as string | null,
      shareToken: row.share_token as string,
      messageCount: (row.message_count || 0) as number,
      status: (row.status || 'active') as string,
      createdAt: (row.created_at || null) as string | null,
    }));
  }

  async deleteShare(shareId: string): Promise<void> {
    await this.request<unknown>(`/v1/shares/${shareId}?network=${this.workspaceId}`, {
      method: 'DELETE',
    });
  }

}

export const workspaceApi = new WorkspaceApi();
