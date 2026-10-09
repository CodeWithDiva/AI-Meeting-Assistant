/**
 * Demo mode — lets the frontend run with no backend (e.g. a static Vercel deploy).
 *
 * Enabled with NEXT_PUBLIC_DEMO_MODE=true. Every API call is answered in the
 * browser from demo-data.json, which was recorded from a real backend running
 * on a sample workspace, so the shapes match the live API exactly. Task, message
 * and meeting edits are kept in memory for the visit. Anything that needs the
 * local machine (joining a meeting, transcription, voice) explains that instead.
 */
import fixtures from "./demo-data.json";

export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export const DEMO_EMAIL = "ayesha@nexora-demo.com";
export const DEMO_PASSWORD = "DemoPass2026!";

const LOCAL_ONLY =
  "This is a read-only demo. Joining meetings, transcription and voice run on the assistant's local backend.";

type Json = any;
const data = fixtures as Record<string, Json>;
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

// One task list is the source of truth, so an edit shows up on every page.
let tasks: Json[] = clone(data["/api/tasks"] ?? []);
let meetings: Json[] = clone(data["/api/meetings"] ?? []);
const messages: Record<string, Json[]> = {};
let nextId = 1000;

function fail(message: string): never {
  throw new Error(message);
}

function meetingDetail(id: number): Json {
  const detail = data[`/api/meetings/${id}`];
  const meeting = meetings.find((m) => m.id === id);
  if (!meeting) fail("Meeting not found.");
  return {
    ...(detail ? clone(detail) : { summary: null, decisions: [], segments: [] }),
    ...meeting,
    action_items: tasks.filter((t) => t.meeting_id === id),
  };
}

function answerFrom(question: string, meetingId?: number) {
  const pool = meetingId ? [meetingDetail(meetingId)] : meetings.map((m) => meetingDetail(m.id));
  const withSummary = pool.filter((m) => m.summary?.text);
  const answer = withSummary.length
    ? withSummary
        .map((m) => {
          const decisions = (m.decisions ?? []).map((d: Json) => `• ${d.text}`).join("\n");
          return `${m.title}: ${m.summary.text}${decisions ? `\n\nDecisions:\n${decisions}` : ""}`;
        })
        .join("\n\n")
    : "There is nothing in these meetings about that yet.";
  // Meeting chat returns source titles; workspace chat returns {meeting_id, title}.
  const sources = meetingId
    ? withSummary.map((m) => m.title)
    : withSummary.map((m) => ({ meeting_id: m.id, title: m.title }));
  return { question, answer, sources };
}

function searchWorkspace(query: string) {
  const q = query.toLowerCase();
  const all = meetings.map((m) => meetingDetail(m.id));
  return {
    query,
    meetings: all.filter((m) => m.title.toLowerCase().includes(q)).map(({ id, title, platform, created_at }) => ({ id, title, platform, created_at })),
    transcript: all.flatMap((m) =>
      (m.segments ?? [])
        .filter((s: Json) => s.text.toLowerCase().includes(q))
        .map((s: Json) => ({ meeting_id: m.id, meeting_title: m.title, speaker: s.speaker_label, text: s.text, start_time: s.start_time }))
    ),
    decisions: all.flatMap((m) =>
      (m.decisions ?? []).filter((d: Json) => d.text.toLowerCase().includes(q)).map((d: Json) => ({ meeting_id: m.id, meeting_title: m.title, text: d.text }))
    ),
    tasks: tasks.filter((t) => t.task.toLowerCase().includes(q)),
  };
}

export async function demoRequest<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, 120));
  return clone(route(endpoint, (options.method || "GET").toUpperCase(), options.body ? JSON.parse(String(options.body)) : {})) as T;
}

function route(endpoint: string, method: string, body: Json): Json {
  const url = new URL(endpoint, "http://demo");
  const path = url.pathname;
  const meetingMatch = /^\/api\/meetings\/(\d+)(\/.*)?$/.exec(path);
  const meetingId = meetingMatch ? Number(meetingMatch[1]) : undefined;
  const sub = meetingMatch?.[2] ?? "";

  if (method === "GET") {
    if (path === "/api/meetings") return meetings;
    if (meetingId !== undefined && sub === "") return meetingDetail(meetingId);
    if (path === "/api/tasks") {
      const status = url.searchParams.get("status");
      return status ? tasks.filter((t) => t.status === status) : tasks;
    }
    const taskMeeting = /^\/api\/tasks\/meeting\/(\d+)$/.exec(path);
    if (taskMeeting) return tasks.filter((t) => t.meeting_id === Number(taskMeeting[1]));
    if (path === "/api/workspace/search") return searchWorkspace(url.searchParams.get("q") ?? "");
    const thread = /^\/api\/messages\/thread\/(\d+)$/.exec(path);
    if (thread) return [...(data[path] ?? []), ...(messages[thread[1]] ?? [])];
    if (path in data) return data[path];
    if (meetingId !== undefined) return data[`/api/meetings/1${sub}`] ?? fail(LOCAL_ONLY);
    return fail(LOCAL_ONLY);
  }

  if (["/api/auth/login", "/api/auth/setup", "/api/auth/accept-invite"].includes(path)) return data.login;
  if (path === "/api/auth/register") return data.login.user;
  if (path === "/api/auth/me") return { ...data["/api/auth/me"], ...body };

  if (path === "/api/meetings" && method === "POST") {
    const meeting = { id: nextId++, title: body.title, platform: body.platform, transcript: null, created_at: new Date().toISOString() };
    meetings = [meeting, ...meetings];
    return meeting;
  }
  if (meetingId !== undefined && sub === "" && method === "PATCH") {
    meetings = meetings.map((m) => (m.id === meetingId ? { ...m, ...body } : m));
    return meetings.find((m) => m.id === meetingId);
  }
  if (meetingId !== undefined && sub === "/analyze") {
    const detail = meetingDetail(meetingId);
    return {
      summary: detail.summary?.text ?? "",
      decisions: (detail.decisions ?? []).map((d: Json) => d.text),
      action_items: detail.action_items.map((t: Json) => ({ assignee: t.assignee, task: t.task, deadline: t.deadline, assigned_by: t.assigned_by })),
    };
  }
  if (meetingId !== undefined && sub === "/chat/ask") return answerFrom(body.question, meetingId);
  if (meetingId !== undefined && sub === "/search") {
    const q = String(body.query || "").toLowerCase();
    const results = (meetingDetail(meetingId).segments ?? [])
      .filter((s: Json) => s.text.toLowerCase().includes(q))
      .map((s: Json) => ({ segment_id: s.id, text: s.text, speaker_label: s.speaker_label, start_time: s.start_time, end_time: s.end_time, score: 1 }));
    return { query: body.query, total_matches: results.length, results };
  }
  if (path === "/api/workspace/ask") return answerFrom(body.question);

  const taskEdit = /^\/api\/tasks\/(\d+)$/.exec(path);
  if (taskEdit && method === "PATCH") {
    const id = Number(taskEdit[1]);
    tasks = tasks.map((t) =>
      t.id === id ? { ...t, ...body, completed_at: body.status === "done" ? new Date().toISOString() : t.completed_at } : t
    );
    return tasks.find((t) => t.id === id);
  }
  const taskCreate = /^\/api\/tasks\/meeting\/(\d+)$/.exec(path);
  if (taskCreate && method === "POST") {
    const meeting = meetings.find((m) => m.id === Number(taskCreate[1]));
    const task = { id: nextId++, meeting_id: meeting?.id, meeting_title: meeting?.title, status: "pending", priority: "medium", ...body, created_at: new Date().toISOString() };
    tasks = [task, ...tasks];
    return task;
  }

  if (path.startsWith("/api/notifications")) return { status: "ok", count: 0 };
  if (path === "/api/messages" && method === "POST") {
    const message = { id: nextId++, sender_id: data.login.user.id, recipient_id: body.recipient_id, body: body.body, read_at: null, created_at: new Date().toISOString() };
    (messages[String(body.recipient_id)] ??= []).push(message);
    return message;
  }

  return fail(LOCAL_ONLY);
}

/** Deletes that the real client sends as bare fetches. */
export function demoDelete(endpoint: string) {
  const meeting = /^\/api\/meetings\/(\d+)$/.exec(endpoint);
  if (meeting) {
    meetings = meetings.filter((m) => m.id !== Number(meeting[1]));
    tasks = tasks.filter((t) => t.meeting_id !== Number(meeting[1]));
  }
  const task = /^\/api\/tasks\/(\d+)$/.exec(endpoint);
  if (task) tasks = tasks.filter((t) => t.id !== Number(task[1]));
}

export function demoLocalOnly(): never {
  return fail(LOCAL_ONLY);
}
