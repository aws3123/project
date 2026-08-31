import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import type { ReviewTask } from '../types/review'
import type { ReviewTaskStatus } from './status'

interface TaskState {
  tasks: Record<string, ReviewTask>
  upsertTasks: (items: ReviewTask[]) => void
  updateStatus: (taskId: string, status: ReviewTaskStatus) => void
  patchTask: (taskId: string, patch: Partial<ReviewTask>) => void
  clear: () => void
}

export const useTaskStore = create<TaskState>()(
  immer((set) => ({
    tasks: {},
    upsertTasks: (items) =>
      set((state) => {
        for (const item of items) {
          state.tasks[item.taskId] = item
        }
      }),
    updateStatus: (taskId, status) =>
      set((state) => {
        if (state.tasks[taskId]) {
          state.tasks[taskId].status = status
        }
      }),
    patchTask: (taskId, patch) =>
      set((state) => {
        if (state.tasks[taskId]) {
          state.tasks[taskId] = { ...state.tasks[taskId], ...patch }
        }
      }),
    clear: () => set({ tasks: {} }),
  })),
)

export function selectTask(taskId: string) {
  return (state: TaskState) => state.tasks[taskId]
}
