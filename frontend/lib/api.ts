/**
 * Centralized API Client & TypeScript Interfaces for AI Meeting Assistant v3
 */

export interface User {
  id: number;
  email: string;
  full_name?: string | null;
  role?: "admin" | "employee" | string;
  created_at?: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Segment {
  id?: number;
  speaker_label?: string | null;
  text: string;
  start_time: number;
  end_time: number;
  source?: string;
  created_at?: string | null;
}

export interface Decision {
  id: number;
  text: string;
}

export type TaskPriority = "low" | "medium" | "high";
export type TaskStatus = "pending" | "in_progress" | "done";

export interface ActionItem {
  id: number;
  meeting_id: number;
  meeting_title?: string | null;
  assignee?: string | null;
  assignee_user_id?: number | null;
  assignee_email?: string | null;
  assigned_by?: string | null;
  task: string;
  deadline?: string | null;
  due_at?: string | null;
  priority: TaskPriority | string;
  status: TaskStatus | string;
  is_overdue?: boolean;
  completed_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface Summary {
  id: number;
  text: string;
  provider: string;
  generated_at?: string | null;
}

export interface Meeting {
  id: number;
  title: string;
  platform?: string | null;
  transcript?: string | null;
  scheduled_at?: string | null;
  ended_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MeetingDetail extends Meeting {
  summary?: Summary | null;
  decisions: Decision[];
  action_items: ActionItem[];
  segments: Segment[];
}

export interface MeetingInsights {
  meeting_id: number;
  participants: Array<{
    speaker: string;
    talk_time_seconds: number;
    talk_time_percent: number;
    engagement_score: number;
    coaching_tip: string;
  }>;
  sentiment: null;
}

export interface DashboardStats {
  total_meetings: number;
  total_tasks: number;
  pending_tasks: number;
  in_progress_tasks: number;
  done_tasks: number;
  recent_meetings: number;
  overdue_tasks: number;
  due_soon_tasks: number;
  my_open_tasks: number;
  completion_rate: number;
}

export interface Recording {
  id: number;
  meeting_id: number;
  enabled: boolean;
  consent_given_at?: string | null;
  file_path?: string | null;
  file_size_bytes?: number | null;
  created_at?: string | null;
}

/** Lifecycle the agent reports, also pushed over WS as `agent_state`. */
export type AgentState =
  | "idle"
  | "SCHEDULED"
  | "JOINING"
  | "IN_MEETING"
  | "PROCESSING"
  | "COMPLETE"
  | "FAILED_JOIN"
  | "DISCONNECTED";

export type MeetingPlatform = "zoom" | "google_meet";

export interface AgentStatus {
  meeting_id?: number | null;
  state: AgentState;
  platform?: MeetingPlatform | string | null;
  is_connected: boolean;
  /** True when the browser/audio hardware is missing and no real audio flows. */
  simulated: boolean;
  active_speaker?: string | null;
  participants: string[];
  error?: string | null;
  /** Attach mode only: whether your own mic is being captured (null elsewhere). */
  mic_captured?: boolean | null;
}

export interface AgentJoinResult {
  meeting_id: number;
  platform: MeetingPlatform | string;
  state: AgentState;
  title: string;
  recording_enabled: boolean;
  message: string;
}

export interface AgentNotesReport {
  decisions?: number;
  action_items?: number;
  assigned?: number;
  unassigned?: number;
}

export interface AgentLeaveResult {
  meeting_id: number;
  state: AgentState;
  message: string;
  notes: AgentNotesReport;
}

/** Which optional parts of the stack are actually installed / configured on the server. */
export interface SystemCapabilities {
  assistant_name: string;
  wake_word: string;
  email_notifications: boolean;
  virtual_microphone: boolean;
  platforms: string[];
  browser_automation: boolean;
  audio_devices: boolean;
  transcription: boolean;
  whisper_model: string;
  llm_model: string;
  tts: boolean;
}

export interface Speaker {
  id: number;
  meeting_id: number;
  speaker_label: string;
  display_name: string | null;
}

export interface SearchMatch {
  segment_id: number;
  text: string;
  speaker_label: string | null;
  start_time: number;
  end_time: number;
  score: number;
}

export interface SearchResponse {
  query: string;
  total_matches: number;
  results: SearchMatch[];
}

export interface ChatAnswer {
  question: string;
  answer: string;
  sources: string[];
}

export interface WorkspaceAnswer {
  question: string;
  answer: string;
  sources: Array<{ meeting_id: number; title: string }>;
}

export interface NotificationItem {
  id: number;
  user_id: number;
  meeting_id?: number | null;
  type: string;
  title: string;
  body?: string | null;
  read: boolean;
  created_at?: string | null;
}

export interface AdminUser {
  id: number;
  email: string;
  full_name?: string | null;
  role: "admin" | "employee" | string;
  /** "invited" — added by an admin, hasn't set a password yet. "active" — can sign in. */
  status: "invited" | "active";
  created_at?: string | null;
  meeting_count: number;
  task_count: number;
  open_tasks: number;
  overdue_tasks: number;
  done_tasks: number;
}

export interface InviteResult {
  user: User;
  invite_link: string;
  email_sent: boolean;
}

export interface InviteDetails {
  email: string;
  full_name?: string | null;
  workspace_name?: string | null;
}

/** Anyone a task can be assigned to. */
export interface TeamMember {
  id: number;
  email: string;
  full_name?: string | null;
  role: "admin" | "employee" | string;
}

export interface WorkspaceSearchResult {
  query: string;
  meetings: Array<{ id: number; title: string; platform?: string | null; created_at?: string | null }>;
  transcript: Array<{ meeting_id: number; meeting_title: string; speaker: string | null; text: string; start_time: number }>;
  decisions: Array<{ meeting_id: number; meeting_title: string; text: string }>;
  tasks: ActionItem[];
}

export interface AdminAnalytics {
  totals: {
    members: number;
    meetings: number;
    meetings_this_week: number;
    tasks: number;
    open_tasks: number;
    overdue_tasks: number;
    unassigned_open_tasks: number;
    completion_rate: number;
  };
  status_counts: { pending: number; in_progress: number; done: number };
  weeks: Array<{ week_start: string; meetings: number; tasks_created: number; tasks_completed: number }>;
  workload: Array<{
    user_id: number;
    name: string;
    email: string;
    role: string;
    meetings_owned: number;
    assigned: number;
    open: number;
    overdue: number;
    done: number;
    completion_rate: number | null;
  }>;
  overdue: ActionItem[];
}

/** Person-to-person direct messaging — admin<->employee or employee<->employee. */
export interface DirectMessage {
  id: number;
  sender_id: number;
  recipient_id: number;
  body: string;
  read_at?: string | null;
  created_at: string;
}

export interface Conversation {
  user: TeamMember;
  last_message: DirectMessage | null;
  unread_count: number;
}

export interface VoiceReplyResult {
  triggered?: boolean;
  message?: string;
  tip?: string;
  question: string;
  answer: string;
  audio_base64: string;
  content_type: string;
  timestamp: string;
  has_audio?: boolean;
  ws_clients_notified?: number;
}

export function getApiBase(): string {
  if (typeof window !== "undefined") {
    const host = window.location.hostname || "localhost";
    return `http://${host}:8000`;
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
}

export const authStorage = {
  getToken(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("meeting_token");
  },
  setToken(token: string) {
    if (typeof window === "undefined") return;
    localStorage.setItem("meeting_token", token);
  },
  clearToken() {
    if (typeof window === "undefined") return;
    localStorage.removeItem("meeting_token");
  },
  isLoggedIn(): boolean {
    return !!authStorage.getToken();
  },
};

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = authStorage.getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${getApiBase()}${endpoint}`, {
    ...options,
    headers,
  });

  const data = await response.json().catch(() => ({}));

  if (response.status === 401) {
    if (typeof window !== "undefined" && !window.location.pathname.includes("/login")) {
      authStorage.clearToken();
      window.location.href = "/login";
    }
    const errorMsg = data?.detail || "Incorrect email or password.";
    throw new Error(typeof errorMsg === "string" ? errorMsg : JSON.stringify(errorMsg));
  }

  if (!response.ok) {
    const errorMsg = data?.detail || data?.message || "An unexpected error occurred";
    throw new Error(typeof errorMsg === "string" ? errorMsg : JSON.stringify(errorMsg));
  }

  return data as T;
}

/** Trigger a file download for an authenticated GET endpoint (blob response). */
async function downloadFile(endpoint: string, fallbackName: string): Promise<void> {
  const token = authStorage.getToken();
  const response = await fetch(`${getApiBase()}${endpoint}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data?.detail || "Download failed.");
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const filename = match?.[1] || fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  // Auth
  /** True on a brand-new install — no accounts exist yet, so the first-run
   *  setup screen should show instead of the login form. */
  async needsSetup(): Promise<boolean> {
    const res = await apiRequest<{ needs_setup: boolean }>("/api/auth/setup-status");
    return res.needs_setup;
  },

  /** Create the workspace's first account, as admin. Only works once — a
   *  workspace that already has anyone in it refuses this permanently. */
  async setupFirstAdmin(email: string, password: string, fullName: string): Promise<AuthResponse> {
    const res = await apiRequest<AuthResponse>("/api/auth/setup", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name: fullName }),
    });
    if (res.access_token) {
      authStorage.setToken(res.access_token);
    }
    return res;
  },

  async login(email: string, password: string): Promise<AuthResponse> {
    const res = await apiRequest<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    if (res.access_token) {
      authStorage.setToken(res.access_token);
    }
    return res;
  },

  async register(email: string, password: string, fullName?: string): Promise<User> {
    return apiRequest<User>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name: fullName || undefined }),
    });
  },

  async getMe(): Promise<User> {
    return apiRequest<User>("/api/auth/me");
  },

  async updateProfile(fullName: string): Promise<User> {
    return apiRequest<User>("/api/auth/me", {
      method: "PATCH",
      body: JSON.stringify({ full_name: fullName }),
    });
  },

  /** Everyone tasks can be assigned to — used to populate the assignee picker. */
  async getTeamMembers(): Promise<TeamMember[]> {
    return apiRequest<TeamMember[]>("/api/auth/users");
  },

  // Meetings
  async getMeetings(): Promise<Meeting[]> {
    return apiRequest<Meeting[]>("/api/meetings");
  },

  async getMeeting(id: number | string): Promise<MeetingDetail> {
    return apiRequest<MeetingDetail>(`/api/meetings/${id}`);
  },

  async getMeetingInsights(id: number | string): Promise<MeetingInsights> {
    return apiRequest<MeetingInsights>(`/api/meetings/${id}/insights`);
  },

  async createMeeting(title: string, platform: string = "zoom"): Promise<Meeting> {
    return apiRequest<Meeting>("/api/meetings", {
      method: "POST",
      body: JSON.stringify({ title, platform }),
    });
  },

  async updateMeeting(
    id: number | string,
    data: { title?: string; platform?: string }
  ): Promise<Meeting> {
    return apiRequest<Meeting>(`/api/meetings/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  async deleteMeeting(id: number | string): Promise<void> {
    const token = authStorage.getToken();
    await fetch(`${getApiBase()}/api/meetings/${id}`, {
      method: "DELETE",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
  },

  /** Download the meeting's notes/transcript as a Markdown file. */
  async exportMeeting(id: number | string, title: string): Promise<void> {
    const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || `meeting-${id}`;
    return downloadFile(`/api/meetings/${id}/export.md`, `${slug}.md`);
  },

  // Audio Upload & Transcription
  async uploadAudio(
    meetingId: number | string,
    file: File
  ): Promise<{ filename: string; transcript: string; segment_count?: number }> {
    const token = authStorage.getToken();
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${getApiBase()}/api/transcription/upload/${meetingId}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: formData,
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Audio upload and transcription failed");
    }
    return data;
  },

  async getTranscript(meetingId: number | string): Promise<{ meeting_id: number; total_segments: number; segments: Segment[] }> {
    return apiRequest(`/api/transcript/${meetingId}`);
  },

  // AI Analysis
  async analyzeMeeting(meetingId: number | string): Promise<{
    summary: string;
    decisions: string[];
    action_items: { assignee: string; task: string; deadline: string | null; assigned_by?: string | null }[];
  }> {
    return apiRequest(`/api/meetings/${meetingId}/analyze`, {
      method: "POST",
    });
  },

  // Tasks
  async getAllTasks(status?: string, scope?: "all" | "assigned" | "created"): Promise<ActionItem[]> {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (scope) params.set("scope", scope);
    const query = params.toString();
    return apiRequest<ActionItem[]>(`/api/tasks${query ? `?${query}` : ""}`);
  },

  async getMeetingTasks(meetingId: number | string): Promise<ActionItem[]> {
    return apiRequest<ActionItem[]>(`/api/tasks/meeting/${meetingId}`);
  },

  async updateTask(
    taskId: number,
    data: {
      status?: string;
      task?: string;
      assignee?: string;
      assignee_user_id?: number | null;
      deadline?: string;
      due_at?: string | null;
      priority?: TaskPriority;
    }
  ): Promise<ActionItem> {
    return apiRequest<ActionItem>(`/api/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  async createTask(
    meetingId: number | string,
    data: {
      task: string;
      assignee?: string;
      assignee_user_id?: number | null;
      assigned_by?: string;
      deadline?: string;
      due_at?: string | null;
      priority?: TaskPriority;
    }
  ): Promise<ActionItem> {
    return apiRequest<ActionItem>(`/api/tasks/meeting/${meetingId}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async deleteTask(taskId: number): Promise<void> {
    const token = authStorage.getToken();
    await fetch(`${getApiBase()}/api/tasks/${taskId}`, {
      method: "DELETE",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
  },

  async downloadTaskInvite(taskId: number, taskText: string): Promise<void> {
    const slug = taskText.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40).replace(/(^-|-$)/g, "");
    return downloadFile(`/api/tasks/${taskId}/calendar.ics`, `${slug || "task"}.ics`);
  },

  // Dashboard Stats
  async getDashboardStats(): Promise<DashboardStats> {
    return apiRequest<DashboardStats>("/api/tasks/dashboard/stats");
  },

  // Recording
  async getRecording(meetingId: number | string): Promise<Recording> {
    return apiRequest<Recording>(`/api/meetings/${meetingId}/recording`);
  },

  async toggleRecording(meetingId: number | string, enabled: boolean): Promise<Recording> {
    return apiRequest<Recording>(`/api/meetings/${meetingId}/recording`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
  },

  // Speakers (Block 2)
  async getSpeakers(meetingId: number | string): Promise<Speaker[]> {
    return apiRequest<Speaker[]>(`/api/meetings/${meetingId}/speakers`);
  },

  async updateSpeakerName(
    meetingId: number | string,
    speakerId: number,
    displayName: string
  ): Promise<Speaker> {
    return apiRequest<Speaker>(`/api/meetings/${meetingId}/speakers/${speakerId}`, {
      method: "PATCH",
      body: JSON.stringify({ display_name: displayName }),
    });
  },

  // Semantic Search (Block 2)
  async searchTranscript(
    meetingId: number | string,
    query: string,
    limit: number = 10
  ): Promise<SearchResponse> {
    return apiRequest<SearchResponse>(`/api/meetings/${meetingId}/search`, {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    });
  },

  /** Search across every meeting, transcript line, decision and task in the workspace. */
  async searchWorkspace(query: string, limit: number = 8): Promise<WorkspaceSearchResult> {
    return apiRequest<WorkspaceSearchResult>(
      `/api/workspace/search?q=${encodeURIComponent(query)}&limit=${limit}`
    );
  },

  // AI Meeting Chat & Q&A Copilot (Block 2)
  async askMeetingQuestion(
    meetingId: number | string,
    question: string
  ): Promise<ChatAnswer> {
    return apiRequest<ChatAnswer>(`/api/meetings/${meetingId}/chat/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    });
  },

  /** Ask Alina something grounded across every meeting in the workspace, not just one. */
  async askWorkspace(question: string): Promise<WorkspaceAnswer> {
    return apiRequest<WorkspaceAnswer>("/api/workspace/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
  },

  /**
   * Same as `askWorkspace`, but calls `onChunk` as the answer streams in —
   * a "written" answer can take 20-40s on modest hardware, and seeing it
   * appear word-by-word reads as working, not stuck. Sources arrive only at
   * the very end (they're not something that can stream incrementally).
   */
  async askWorkspaceStream(
    question: string,
    onChunk: (textSoFar: string) => void
  ): Promise<{ question: string; answer: string; sources: Array<{ meeting_id: number; title: string }> }> {
    const token = authStorage.getToken();
    const response = await fetch(`${getApiBase()}/api/workspace/ask/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ question }),
    });
    if (!response.ok || !response.body) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data?.detail || "Alina couldn't answer that right now.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let raw = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      raw += decoder.decode(value, { stream: true });
      // The sources marker only ever appears as the final chunk, but guard
      // mid-stream too in case it arrives split across two reads.
      const markerIndex = raw.indexOf("␟");
      onChunk(markerIndex >= 0 ? raw.slice(0, markerIndex) : raw);
    }

    const markerIndex = raw.indexOf("␟");
    const answer = (markerIndex >= 0 ? raw.slice(0, markerIndex) : raw).replace(/\n$/, "");
    let sources: Array<{ meeting_id: number; title: string }> = [];
    if (markerIndex >= 0) {
      try {
        sources = JSON.parse(raw.slice(markerIndex + 1));
      } catch {
        sources = [];
      }
    }
    return { question, answer, sources };
  },

  // Text-to-Speech (Block 3)
  async speakText(meetingId: number | string, text: string): Promise<{ audio_base64: string; content_type: string }> {
    return apiRequest<{ audio_base64: string; content_type: string }>(`/api/meetings/${meetingId}/tts/speak`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  },

  // WebSocket Live Streaming (Block 3)
  getLiveWebSocketUrl(meetingId: number | string): string {
    const token = authStorage.getToken() || "";
    const base = getApiBase().replace(/^http/, "ws");
    return `${base}/ws/meetings/${meetingId}/live?token=${encodeURIComponent(token)}`;
  },

  // Meeting agent — paste a link and the assistant joins.
  // The join runs in the background; watch `agent_state` on the meeting
  // WebSocket for JOINING → IN_MEETING → PROCESSING → COMPLETE.
  //
  // mode "agent"  — the browser bot joins the meeting itself (Zoom or Google Meet).
  // mode "attach" — you join the meeting in your own app; the assistant only
  //                 listens through the capture device (link optional, title used).
  async sendAgentToMeeting(
    link: string,
    options: {
      title?: string;
      record?: boolean;
      mode?: "agent" | "attach";
      /** mode="attach" only: your name, used to label your own voice in the transcript. */
      displayName?: string;
    } = {}
  ): Promise<AgentJoinResult> {
    return apiRequest<AgentJoinResult>("/api/agent/join", {
      method: "POST",
      body: JSON.stringify({
        mode: options.mode ?? "agent",
        link: link || undefined,
        title: options.title,
        record: options.record ?? false,
        display_name: options.displayName || undefined,
      }),
    });
  },

  async joinExistingMeeting(meetingId: number | string, link: string, record: boolean = false): Promise<AgentJoinResult> {
    return apiRequest<AgentJoinResult>(`/api/agent/join/${meetingId}`, {
      method: "POST",
      body: JSON.stringify({ link, record }),
    });
  },

  async leaveMeeting(meetingId: number | string): Promise<AgentLeaveResult> {
    return apiRequest<AgentLeaveResult>(`/api/agent/leave/${meetingId}`, {
      method: "POST",
    });
  },

  async getAgentStatus(meetingId: number | string): Promise<AgentStatus> {
    return apiRequest<AgentStatus>(`/api/agent/status/${meetingId}`);
  },

  async getActiveAgentSessions(): Promise<AgentStatus[]> {
    return apiRequest<AgentStatus[]>("/api/agent/sessions");
  },

  async getSystemCapabilities(): Promise<SystemCapabilities> {
    return apiRequest<SystemCapabilities>("/api/system/capabilities");
  },

  // Notifications
  async getNotifications(unreadOnly: boolean = false): Promise<NotificationItem[]> {
    return apiRequest<NotificationItem[]>(`/api/notifications${unreadOnly ? "?unread_only=true" : ""}`);
  },

  async getUnreadNotificationCount(): Promise<number> {
    const res = await apiRequest<{ unread: number }>("/api/notifications/unread-count");
    return res.unread;
  },

  async markNotificationRead(notificationId: number): Promise<NotificationItem> {
    return apiRequest<NotificationItem>(`/api/notifications/${notificationId}/read`, {
      method: "PATCH",
    });
  },

  async markAllNotificationsRead(): Promise<{ status: string; count: number }> {
    return apiRequest<{ status: string; count: number }>("/api/notifications/mark-all-read", {
      method: "POST",
    });
  },

  // Admin — Users
  async getAdminUsers(): Promise<AdminUser[]> {
    return apiRequest<AdminUser[]>("/api/auth/admin/users");
  },

  /** Add an employee by name + email only — no password to hand out. Returns a
   *  one-time setup link, always, regardless of whether an email went out. */
  async adminInviteUser(data: { email: string; full_name: string; role: "admin" | "employee" }): Promise<InviteResult> {
    return apiRequest<InviteResult>("/api/auth/admin/users", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async adminResendInvite(userId: number): Promise<InviteResult> {
    return apiRequest<InviteResult>(`/api/auth/admin/users/${userId}/resend-invite`, {
      method: "POST",
    });
  },

  async adminUpdateUser(userId: number, data: { full_name?: string; role?: "admin" | "employee" }): Promise<User> {
    return apiRequest<User>(`/api/auth/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  async adminDeleteUser(userId: number): Promise<void> {
    const token = authStorage.getToken();
    await fetch(`${getApiBase()}/api/auth/admin/users/${userId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
  },

  // Invites — accepted by the invited person, no auth required
  async getInvite(inviteToken: string): Promise<InviteDetails> {
    return apiRequest<InviteDetails>(`/api/auth/invite/${inviteToken}`);
  },

  async acceptInvite(inviteToken: string, password: string): Promise<AuthResponse> {
    const res = await apiRequest<AuthResponse>("/api/auth/accept-invite", {
      method: "POST",
      body: JSON.stringify({ token: inviteToken, password }),
    });
    if (res.access_token) authStorage.setToken(res.access_token);
    return res;
  },

  /** Admin-only: meeting volume, task health, and each member's workload. */
  async getAdminAnalytics(): Promise<AdminAnalytics> {
    return apiRequest<AdminAnalytics>("/api/admin/analytics");
  },

  // Voice Reply — manual test (dev/prod)
  async testVoiceReply(
    meetingId: number | string,
    text: string
  ): Promise<VoiceReplyResult> {
    return apiRequest<VoiceReplyResult>(
      `/api/meetings/${meetingId}/voice-reply/test`,
      {
        method: "POST",
        body: JSON.stringify({ text }),
      }
    );
  },

  async getLatestVoiceReply(meetingId: number | string): Promise<{ meeting_id: number; reply: VoiceReplyResult | null }> {
    return apiRequest(`/api/meetings/${meetingId}/voice-reply/latest`);
  },

  // Real-time WebSocket for meeting events (assistant replies, agent state, live transcript)
  getMeetingWebSocketUrl(meetingId: number | string): string {
    const base = getApiBase().replace(/^http/, "ws");
    return `${base}/api/meetings/${meetingId}/ws`;
  },

  // Direct messages — plain chat between two people, not meeting-scoped.
  async getConversations(): Promise<Conversation[]> {
    return apiRequest<Conversation[]>("/api/messages/conversations");
  },

  async getUnreadMessageCount(): Promise<number> {
    const res = await apiRequest<{ unread: number }>("/api/messages/unread-count");
    return res.unread;
  },

  async getMessageThread(otherUserId: number | string): Promise<DirectMessage[]> {
    return apiRequest<DirectMessage[]>(`/api/messages/thread/${otherUserId}`);
  },

  async sendDirectMessage(recipientId: number, body: string): Promise<DirectMessage> {
    return apiRequest<DirectMessage>("/api/messages", {
      method: "POST",
      body: JSON.stringify({ recipient_id: recipientId, body }),
    });
  },

  getMessagesWebSocketUrl(): string {
    const token = authStorage.getToken() || "";
    const base = getApiBase().replace(/^http/, "ws");
    return `${base}/api/messages/ws?token=${encodeURIComponent(token)}`;
  },
};
