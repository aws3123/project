import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import type { ReviewResult } from '../types/review'

interface ResultState {
  results: Record<string, ReviewResult>
  setResult: (result: ReviewResult) => void
  clear: () => void
}

export const useResultStore = create<ResultState>()(
  immer((set) => ({
    results: {},
    setResult: (result) =>
      set((state) => {
        state.results[result.taskId] = result
      }),
    clear: () => set({ results: {} }),
  })),
)

export const selectResult = (taskId: string) => (state: ResultState) => state.results[taskId]
