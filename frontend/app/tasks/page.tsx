"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ActionItem, api, authStorage } from "@/lib/api";

type KanbanColumn = "pending" | "in_progress" | "done";

const COLUMNS: { key: KanbanColumn; label: string; icon: string; color: string }[] = [
  { key: "pending", label: "Pending", icon: "⏳", color: "var(--accent-amber)" },
  { key: "in_progress", label: "In Progress", icon: "🔄", color: "var(--accent-cyan)" },
  { key: "done", label: "Done", icon: "✅", color: "var(--accent-emerald)" },
];

export default function TasksPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState<ActionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [selectedTask, setSelectedTask] = useState<ActionItem | null>(null);
  const [dragOverCol, setDragOverCol] = useState<KanbanColumn | null>(null);
  const [dragTaskId, setDragTaskId] = useState<number | null>(null);

  useEffect(() => {
    if (!authStorage.isLoggedIn()) { router.push("/login"); return; }
    loadTasks();
  }, [router]);

  async function loadTasks() {
    setLoading(true);
    try {
      const data = await api.getAllTasks();
      setTasks(data);
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
    } catch (e: any) {
      setError(e.message || "Failed to update task");
    } finally {
      setUpdatingId(null);
    }
  }

  function onDragStart(e: React.DragEvent, taskId: number) {
    setDragTaskId(taskId);
    e.dataTransfer.effectAllowed = "move";
  }

  function onDrop(e: React.DragEvent, col: KanbanColumn) {
    e.preventDefault();
    if (dragTaskId !== null) {
      moveTask(dragTaskId, col);
    }
    setDragOverCol(null);
    setDragTaskId(null);
  }

  function formatDate(d: string | null | undefined) {
    if (!d) return null;
    return new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  const tasksByStatus = (status: KanbanColumn) => tasks.filter((t) => t.status === status);

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-primary)" }}>
        <div className="spinner" />
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-primary)", color: "var(--text-primary)" }}>
      {/* Header */}
      <header style={{ background: "var(--bg-glass)", borderBottom: "1px solid var(--border-subtle)", padding: "1rem 2rem", display: "flex", alignItems: "center", gap: "1rem", backdropFilter: "blur(12px)", position: "sticky", top: 0, zIndex: 50 }}>
        <Link href="/dashboard" style={{ color: "var(--text-muted)", textDecoration: "none", fontSize: "0.875rem" }}>← Dashboard</Link>
        <h1 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, background: "linear-gradient(135deg, var(--accent-cyan), var(--accent-emerald))", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
          My Tasks
        </h1>
        <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: "0.875rem" }}>{tasks.length} total tasks</span>
        <button onClick={loadTasks} className="btn-ghost" style={{ padding: "0.4rem 0.8rem", fontSize: "0.8rem" }}>↻ Refresh</button>
      </header>

      {error && (
        <div style={{ margin: "1rem 2rem", padding: "0.75rem 1rem", background: "rgba(239,68,68,0.15)", border: "1px solid rgba(239,68,68,0.4)", borderRadius: "0.5rem", color: "#f87171", fontSize: "0.875rem" }}>
          {error}
        </div>
      )}

      {/* Kanban Board */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1.5rem", padding: "2rem", maxWidth: "1400px", margin: "0 auto" }}>
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
                background: isOver ? "rgba(255,255,255,0.06)" : "var(--bg-card)",
                border: `1px solid ${isOver ? col.color : "var(--border-subtle)"}`,
                borderRadius: "1rem",
                padding: "1.25rem",
                transition: "all 0.2s ease",
                boxShadow: isOver ? `0 0 20px ${col.color}33` : "none",
                minHeight: "400px",
              }}
            >
              {/* Column header */}
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1.25rem" }}>
                <span style={{ fontSize: "1.1rem" }}>{col.icon}</span>
                <span style={{ fontWeight: 600, color: col.color }}>{col.label}</span>
                <span style={{ marginLeft: "auto", background: "var(--bg-glass)", padding: "0.15rem 0.55rem", borderRadius: "9999px", fontSize: "0.75rem", color: "var(--text-muted)" }}>{colTasks.length}</span>
              </div>

              {/* Task cards */}
              <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                {colTasks.length === 0 && (
                  <div style={{ textAlign: "center", color: "var(--text-muted)", fontSize: "0.85rem", padding: "2rem 0" }}>
                    No tasks here
                  </div>
                )}
                {colTasks.map((task) => (
                  <div
                    key={task.id}
                    draggable
                    onDragStart={(e) => onDragStart(e, task.id)}
                    onClick={() => setSelectedTask(task)}
                    style={{
                      background: "var(--bg-glass)",
                      border: "1px solid var(--border-subtle)",
                      borderLeft: `3px solid ${col.color}`,
                      borderRadius: "0.625rem",
                      padding: "0.875rem",
                      cursor: "grab",
                      transition: "transform 0.15s ease, box-shadow 0.15s ease",
                      opacity: updatingId === task.id ? 0.5 : 1,
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLDivElement).style.transform = "translateY(-2px)";
                      (e.currentTarget as HTMLDivElement).style.boxShadow = `0 4px 20px ${col.color}22`;
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLDivElement).style.transform = "translateY(0)";
                      (e.currentTarget as HTMLDivElement).style.boxShadow = "none";
                    }}
                  >
                    <p style={{ margin: "0 0 0.5rem 0", fontSize: "0.875rem", fontWeight: 500, lineHeight: 1.4 }}>{task.task}</p>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", fontSize: "0.75rem", color: "var(--text-muted)" }}>
                      {task.assignee && <span style={{ background: "var(--bg-primary)", padding: "0.15rem 0.5rem", borderRadius: "9999px" }}>👤 {task.assignee}</span>}
                      {task.deadline && <span style={{ background: "var(--bg-primary)", padding: "0.15rem 0.5rem", borderRadius: "9999px" }}>📅 {task.deadline}</span>}
                    </div>
                    {/* Quick status buttons */}
                    <div style={{ display: "flex", gap: "0.35rem", marginTop: "0.625rem", flexWrap: "wrap" }}>
                      {COLUMNS.filter((c) => c.key !== col.key).map((c) => (
                        <button
                          key={c.key}
                          onClick={(e) => { e.stopPropagation(); moveTask(task.id, c.key); }}
                          style={{ fontSize: "0.7rem", padding: "0.2rem 0.5rem", borderRadius: "9999px", border: `1px solid ${c.color}44`, background: "transparent", color: c.color, cursor: "pointer" }}
                        >
                          → {c.label}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Task detail popup */}
      {selectedTask && (
        <div
          onClick={() => setSelectedTask(null)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, backdropFilter: "blur(4px)" }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: "1.25rem", padding: "2rem", maxWidth: "500px", width: "90%", boxShadow: "0 25px 60px rgba(0,0,0,0.5)" }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.25rem" }}>
              <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700 }}>Task Details</h3>
              <button onClick={() => setSelectedTask(null)} style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "1.2rem" }}>✕</button>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.875rem" }}>
              <p style={{ margin: 0, fontSize: "0.95rem", lineHeight: 1.6 }}>{selectedTask.task}</p>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", fontSize: "0.85rem" }}>
                <div style={{ background: "var(--bg-glass)", padding: "0.75rem", borderRadius: "0.5rem" }}>
                  <div style={{ color: "var(--text-muted)", marginBottom: "0.25rem" }}>Assignee</div>
                  <div style={{ fontWeight: 500 }}>{selectedTask.assignee || "Unassigned"}</div>
                </div>
                <div style={{ background: "var(--bg-glass)", padding: "0.75rem", borderRadius: "0.5rem" }}>
                  <div style={{ color: "var(--text-muted)", marginBottom: "0.25rem" }}>Deadline</div>
                  <div style={{ fontWeight: 500 }}>{selectedTask.deadline || "No deadline"}</div>
                </div>
                <div style={{ background: "var(--bg-glass)", padding: "0.75rem", borderRadius: "0.5rem" }}>
                  <div style={{ color: "var(--text-muted)", marginBottom: "0.25rem" }}>Status</div>
                  <div style={{ fontWeight: 500, textTransform: "capitalize" }}>{selectedTask.status.replace("_", " ")}</div>
                </div>
                <div style={{ background: "var(--bg-glass)", padding: "0.75rem", borderRadius: "0.5rem" }}>
                  <div style={{ color: "var(--text-muted)", marginBottom: "0.25rem" }}>Created</div>
                  <div style={{ fontWeight: 500 }}>{formatDate(selectedTask.created_at) || "—"}</div>
                </div>
              </div>
              <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
                {COLUMNS.map((col) => (
                  <button
                    key={col.key}
                    onClick={() => { moveTask(selectedTask.id, col.key); setSelectedTask(null); }}
                    disabled={selectedTask.status === col.key}
                    style={{
                      flex: 1, padding: "0.5rem", borderRadius: "0.5rem", border: `1px solid ${col.color}`,
                      background: selectedTask.status === col.key ? `${col.color}22` : "transparent",
                      color: col.color, cursor: selectedTask.status === col.key ? "default" : "pointer",
                      fontSize: "0.8rem", fontWeight: 600, opacity: selectedTask.status === col.key ? 0.7 : 1,
                    }}
                  >
                    {col.icon} {col.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
