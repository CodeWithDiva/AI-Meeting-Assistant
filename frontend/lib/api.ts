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

export interface ActionItem {
  id: number;
  meeting_id: number;
  assignee?: string | null;
  assigned_by?: string | null;
  task: string;
  deadline?: string | null;
  status: "pending" | "in_progress" | "done" | string;
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
  done_tasks: number;
  recent_meetings: number;
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

export interface AgentStatus {
  state: "idle" | "joining" | "listening" | "processing" | "answering" | "leaving" | "stopped" | string;
  meeting_id?: number | null;
  mode?: string;
  error?: string | null;
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
  created_at?: string | null;
  meeting_count: number;
  task_count: number;
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

export const api = {
  // Auth
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

  async register(email: string, password: string): Promise<User> {
    return apiRequest<User>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  async getMe(): Promise<User> {
    return apiRequest<User>("/api/auth/me");
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
  async getAllTasks(status?: string): Promise<ActionItem[]> {
    const query = status ? `?status=${status}` : "";
    return apiRequest<ActionItem[]>(`/api/tasks${query}`);
  },

  async getMeetingTasks(meetingId: number | string): Promise<ActionItem[]> {
    return apiRequest<ActionItem[]>(`/api/tasks/meeting/${meetingId}`);
  },

  async updateTask(
    taskId: number,
    data: { status?: string; task?: string; assignee?: string; deadline?: string }
  ): Promise<ActionItem> {
    return apiRequest<ActionItem>(`/api/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  async createTask(
    meetingId: number | string,
    data: { task: string; assignee?: string; assigned_by?: string; deadline?: string }
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

  // Zoom Bot (Block 4)
  async joinZoomMeeting(meetingId: number | string, zoomUrlOrId: string): Promise<{ status: string; message: string; simulated?: boolean }> {
    return apiRequest<{ status: string; message: string; simulated?: boolean }>(`/api/zoom/join/${meetingId}`, {
      method: "POST",
      body: JSON.stringify({ zoom_url_or_id: zoomUrlOrId }),
    });
  },

  async leaveZoomMeeting(meetingId: number | string): Promise<{ status: string; message: string }> {
    return apiRequest<{ status: string; message: string }>(`/api/zoom/leave/${meetingId}`, {
      method: "POST",
    });
  },

  async getZoomStatus(meetingId: number | string): Promise<{ meeting_id: number; status: string; is_connected: boolean }> {
    return apiRequest<{ meeting_id: number; status: string; is_connected: boolean }>(`/api/zoom/status/${meetingId}`);
  },

  async getZoomAuthorizationUrl(): Promise<{ authorization_url: string }> {
    return apiRequest<{ authorization_url: string }>("/api/integrations/zoom/authorize");
  },

  // Notifications (Block 5)
  async getNotifications(unreadOnly: boolean = false): Promise<NotificationItem[]> {
    return apiRequest<NotificationItem[]>(`/api/notifications${unreadOnly ? "?unread_only=true" : ""}`);
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

  // Simulated / Real Agent
  async getAgentStatus(): Promise<AgentStatus> {
    return apiRequest<AgentStatus>("/api/agent/status");
  },

  async startAgent(meetingId: number | string, mode: string = "simulated"): Promise<{ status: string }> {
    return apiRequest<{ status: string }>("/api/agent/start", {
      method: "POST",
      body: JSON.stringify({ meeting_id: Number(meetingId), mode }),
    });
  },

  async stopAgent(): Promise<{ status: string }> {
    return apiRequest<{ status: string }>("/api/agent/stop", {
      method: "POST",
    });
  },

  // Admin — Users list (admin only)
  async getAdminUsers(): Promise<AdminUser[]> {
    return apiRequest<AdminUser[]>("/api/auth/admin/users");
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

  // Real-time WebSocket for meeting events (Ava replies, agent state, live transcript)
  getMeetingWebSocketUrl(meetingId: number | string): string {
    const base = getApiBase().replace(/^http/, "ws");
    return `${base}/api/meetings/${meetingId}/ws`;
  },
};
