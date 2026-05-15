import { defineStore } from "pinia"

export interface BlockingJobSnapshot {
  tripId: string
  jobId: string
  type: string
  status: string
  stageMessage?: string | null
}

interface JobGuardState {
  activeJob: BlockingJobSnapshot | null
}

export const useJobGuardStore = defineStore("job-guard", {
  state: (): JobGuardState => ({
    activeJob: null
  }),
  getters: {
    hasActiveJob: (state) => Boolean(state.activeJob),
    isNavigationLocked: (state) => Boolean(state.activeJob)
  },
  actions: {
    setActiveJob(payload: BlockingJobSnapshot) {
      this.activeJob = payload
    },
    clearActiveJob() {
      this.activeJob = null
    }
  }
})
