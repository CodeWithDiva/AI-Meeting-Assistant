"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ActionItem, api, authStorage, TaskPriority, TeamMember } from "@/lib/api";
import { dueInfo, formatDate, initials, toLocalInput } from "@/lib/format";
import Icon from "@/app/components/Icon";

type KanbanColumn = "pending" | "in_progress" | "done";

const COLUMNS: { key: KanbanColumn; label: string }[] = [
  { key: "pending", label: "To do" },
  { key: "in_progress", label: "In progress" },
  { key: "done", label: "Done" },
];

const PRIORITIES: TaskPriority[] = ["low", "medium", "high"];

export default function TasksPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState<ActionItem[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [scope, setScope] = useState<"all" | "assigned" | "created">("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [selectedTask, setSelectedTask] = useState<ActionItem | null>(null);
  const [dragOverCol, setDragOverCol] = useState<KanbanColumn | null>(null);
  const [dragTaskId, setDragTaskId] = useState<number | null>(null);
  const [savingDetail, setSavingDetail] = useState(false);

  useEffect(() => {
    if (!authStorage.isLoggedIn()) { router.push("/login"); return; }
    loadTasks();
    api.getTeamMembers().then(setMembers).catch(() => setMembers([]));
  }, [router]);

  useEffect(() => {
    if (!authStorage.isLoggedIn()) return;
    loadTasks();
  }, [scope]);

  async function loadTasks() {
    setLoading(true);
    try {
      setTasks(await api.getAllTasks(undefined, scope));
    } catch (e: any) {
      setError(e.message || "Failed to load tasks");
    } finally {
      setLoading(false);
    }
  }

  async function moveTask(taskId: number, newStatus: KanbanColumn) {
    setUpdatingId(taskId);
    try {
      const updated = await api.updateTask(taskId, { status: newStatus });
      setTasks((prev) => prev.map((t) => (t.id === taskId ? updated : t)));
      setSelectedTask((prev) => (prev && prev.id === taskId ? updated : prev));
    } catch (e: any) {
      setError(e.message || "Failed to update task");
    } finally {
      setUpdatingId(null);
    }
  }

  async function saveDetail(taskId: number, data: Parameters<typeof api.updateTask>[1]) {
    setSavingDetail(true);
    try {
      const updated = await api.updateTask(taskId, data);
      setTasks((prev) => prev.map((t) => (t.id === taskId ? updated : t)));
      setSelectedTask(updated);
    } catch (e: any) {
      setError(e.message || "Failed to update task");
    } finally {
      setSavingDetail(false);
    }
  }

  async function removeTask(taskId: number) {
    if (!confirm("Delete this task?")) return;
    try {
      await api.deleteTask(taskId);
      setTasks((prev) => prev.filter((t) => t.id !== taskId));
      setSelectedTask(null);
    } catch (e: any) {
      setError(e.message || "Failed to delete task");
    }
  }

  function onDragStart(e: React.DragEvent, taskId: number) {
    setDragTaskId(taskId);
    e.dataTransfer.effectAllowed = "move";
  }

  function onDrop(e: React.DragEvent, col: KanbanColumn) {
    e.preventDefault();
    if (dragTaskId !== null) moveTask(dragTaskId, col);
    setDragOverCol(null);
    setDragTaskId(null);
  }

  const tasksByStatus = (status: KanbanColumn) => tasks.filter((t) => t.status === status);

  if (loading) {
    return (
      <div style={{ minHeight: "60vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div className="spinner" style={{ width: 22, height: 22, borderTopColor: "var(--accent-primary)", borderColor: "var(--border-card)" }} />
      </div>
    );
  }

  return (
    <div className="app-container">
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", marginBottom: 6 }}>
        <div>
          <h1 style={{ fontSize: 22, marginBottom: 4 }}>Tasks</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13.5 }}>{tasks.length} task{tasks.length === 1 ? "" : "s"}</p>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <div className="mode-toggle" style={{ margin: 0 }}>
            <button className={scope === "all" ? "is-on" : ""} onClick={() => setScope("all")}>All</button>
            <button className={scope === "assigned" ? "is-on" : ""} onClick={() => setScope("assigned")}>Assigned to me</button>
            <button className={scope === "created" ? "is-on" : ""} onClick={() => setScope("created")}>From my meetings</button>
          </div>
          <button onClick={loadTasks} className="icon-btn" title="Refresh"><Icon name="refresh" size={15} /></button>
        </div>
      </div>

      {error && <div className="alert-box alert-error" style={{ marginTop: 18 }}><Icon name="alert" size={16} />{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginTop: 20 }}>
        {COLUMNS.map((col) => {
          const colTasks = tasksByStatus(col.key);
          const isOver = dragOverCol === col.key;
          return (
            <div
              key={col.key}
              onDragOver={(e) => { e.preventDefault(); setDragOverCol(col.key); }}
              onDragLeave={() => setDragOverCol(null)}
              onDrop={(e) => onDrop(e, col.key)}
              style={{
                background: isOver ? "var(--bg-card-hover)" : "var(--bg-card)",
                border: `1px solid ${isOver ? "var(--border-card-hover)" : "var(--border-card)"}`,
                borderRadius: "var(--radius-lg)", padding: 16, minHeight: 420, transition: "all 0.15s ease",
              }}
            >
              <div className="task-column-title" style={{ marginBottom: 14 }}>
                {col.label} <span>{colTasks.length}</span>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                {colTasks.length === 0 && (
                  <div style={{ textAlign: "center", color: "var(--text-dim)", fontSize: 12.5, padding: "26px 0" }}>Nothing here</div>
                )}
                {colTasks.map((task) => {
                  const due = dueInfo(task);
                  return (
                    <div
                      key={task.id}
                      draggable
                      onDragStart={(e) => onDragStart(e, task.id)}
                      onClick={() => setSelectedTask(task)}
                      style={{
                        background: "var(--bg-surface)", border: "1px solid var(--border-card)",
                        borderRadius: "var(--radius-sm)", padding: "12px 13px", cursor: "grab",
                        opacity: updatingId === task.id ? 0.5 : 1, transition: "border-color 0.12s ease",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "flex-start", gap: 7, marginBottom: 8 }}>
                        <span className={`priority-dot priority-dot-${task.priority}`} style={{ marginTop: 5 }} />
                        <p style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.4 }}>{task.task}</p>
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                        {task.assignee && (
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11.5, color: "var(--text-secondary)" }}>
                            <span className="avatar" style={{ width: 16, height: 16, fontSize: 8 }}>{initials(task.assignee)}</span>
                            {task.assignee}
                          </span>
                        )}
                        {(task.due_at || task.deadline) && (
                          <span className={`due-badge due-${due.tone}`}><Icon name="clock" size={11} />{due.label}</span>
                        )}
                        {task.meeting_title && (
                          <span style={{ fontSize: 11, color: "var(--text-dim)" }}>· {task.meeting_title}</span>
                        )}
                      </div>
                      <div style={{ display: "flex", gap: 6, marginTop: 9, flexWrap: "wrap" }}>
                        {COLUMNS.filter((c) => c.key !== col.key).map((c) => (
                          <button
                            key={c.key}
                            onClick={(e) => { e.stopPropagation(); moveTask(task.id, c.key); }}
                            className="btn btn-ghost btn-sm"
                            style={{ padding: "3px 8px", fontSize: 11 }}
                          >
                            → {c.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {selectedTask && (
        <TaskDetailModal
          task={selectedTask}
          members={members}
          saving={savingDetail}
          onClose={() => setSelectedTask(null)}
          onSave={(data) => saveDetail(selectedTask.id, data)}
          onDelete={() => removeTask(selectedTask.id)}
          onDownloadInvite={() => api.downloadTaskInvite(selectedTask.id, selectedTask.task).catch((e) => setError(e.message))}
        />
      )}
    </div>
  );
}

function TaskDetailModal({
  task, members, saving, onClose, onSave, onDelete, onDownloadInvite,
}: {
  task: ActionItem;
  members: TeamMember[];
  saving: boolean;
  onClose: () => void;
  onSave: (data: Parameters<typeof api.updateTask>[1]) => void;
  onDelete: () => void;
  onDownloadInvite: () => void;
}) {
  const [text, setText] = useState(task.task);
  const [assigneeId, setAssigneeId] = useState<string>(task.assignee_user_id ? String(task.assignee_user_id) : "");
  const [deadline, setDeadline] = useState(task.deadline || "");
  const [dueAt, setDueAt] = useState(toLocalInput(task.due_at));
  const [priority, setPriority] = useState<TaskPriority>((task.priority as TaskPriority) || "medium");

  useEffect(() => {
    setText(task.task);
    setAssigneeId(task.assignee_user_id ? String(task.assignee_user_id) : "");
    setDeadline(task.deadline || "");
    setDueAt(toLocalInput(task.due_at));
    setPriority((task.priority as TaskPriority) || "medium");
  }, [task.id]);

  function commitField(patch: Parameters<typeof onSave>[0]) {
    onSave(patch);
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content" style={{ maxWidth: 520 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <h3 style={{ fontSize: 16 }}>Task details</h3>
          <button onClick={onClose} className="icon-btn" style={{ border: "none" }}><Icon name="x" size={16} /></button>
        </div>

        <div className="form-group">
          <label className="form-label">Description</label>
          <textarea
            className="form-input"
            rows={2}
            style={{ resize: "vertical" }}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onBlur={() => text.trim() && text !== task.task && commitField({ task: text.trim() })}
          />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div className="form-group">
            <label className="form-label">Assignee</label>
            <select
              className="form-input"
              value={assigneeId}
              onChange={(e) => {
                setAssigneeId(e.target.value);
                commitField({ assignee_user_id: e.target.value ? Number(e.target.value) : null });
              }}
            >
              <option value="">Unassigned</option>
              {members.map((m) => (
                <option key={m.id} value={m.id}>{m.full_name || m.email}</option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Priority</label>
            <select className="form-input" value={priority} onChange={(e) => { setPriority(e.target.value as TaskPriority); commitField({ priority: e.target.value as TaskPriority }); }}>
              {PRIORITIES.map((p) => <option key={p} value={p}>{p[0].toUpperCase() + p.slice(1)}</option>)}
            </select>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div className="form-group">
            <label className="form-label">Deadline (free text)</label>
            <input
              type="text"
              className="form-input"
              placeholder="e.g. Friday 5 PM, kal tak"
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
              onBlur={() => deadline !== (task.deadline || "") && commitField({ deadline })}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Exact date &amp; time</label>
            <input
              type="datetime-local"
              className="form-input"
              value={dueAt}
              onChange={(e) => {
                setDueAt(e.target.value);
                commitField({ due_at: e.target.value ? new Date(e.target.value).toISOString() : null });
              }}
            />
          </div>
        </div>

        {task.meeting_title && (
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>From meeting: <strong style={{ color: "var(--text-secondary)" }}>{task.meeting_title}</strong></div>
        )}
        {task.assigned_by && (
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>Assigned by {task.assigned_by} · {formatDate(task.created_at, true)}</div>
        )}

        <div style={{ display: "flex", gap: 6, marginBottom: 18 }}>
          {COLUMNS.map((c) => (
            <button
              key={c.key}
              onClick={() => commitField({ status: c.key })}
              disabled={task.status === c.key}
              className={`btn btn-sm ${task.status === c.key ? "btn-primary" : "btn-secondary"}`}
              style={{ flex: 1 }}
            >
              {c.label}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: "1px solid var(--border-subtle)", paddingTop: 14 }}>
          <button onClick={onDelete} className="btn btn-ghost btn-sm" style={{ color: "var(--accent-rose)" }}><Icon name="trash" size={13} /> Delete</button>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {saving && <span className="spinner" style={{ borderTopColor: "var(--accent-primary)", borderColor: "var(--border-card)" }} />}
            {task.due_at && (
              <button onClick={onDownloadInvite} className="btn btn-secondary btn-sm"><Icon name="calendar" size={13} /> Add to calendar</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
