import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import type { ReviewLogEntry } from '../types/review'

interface LogState {
  logs: Record<string, ReviewLogEntry[]>
  setLogs: (taskId: string, entries: ReviewLogEntry[]) => void
  clear: () => void
}

const EMPTY_LOGS: ReviewLogEntry[] = []

export const useLogStore = create<LogState>()(
  immer((set) => ({
    logs: {},
    setLogs: (taskId, entries) =>
      set((state) => {
        state.logs[taskId] = entries
      }),
    clear: () => set({ logs: {} }),
  })),
)

export const selectLogs = (taskId: string) => (state: LogState) => state.logs[taskId] ?? EMPTY_LOGS
