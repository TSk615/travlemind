import { reactive } from "vue"

const UNAUTHORIZED_NOTICE_COOLDOWN_MS = 1500

interface UnauthorizedSessionState {
  active: boolean
  version: number
}

const state = reactive<UnauthorizedSessionState>({
  active: false,
  version: 0
})

let lastTriggeredAt = 0

export function notifyUnauthorizedSession(): void {
  const now = Date.now()
  if (state.active || now - lastTriggeredAt < UNAUTHORIZED_NOTICE_COOLDOWN_MS) {
    return
  }

  lastTriggeredAt = now
  state.active = true
  state.version += 1
}

export function clearUnauthorizedSessionNotice(): void {
  state.active = false
}

export function useUnauthorizedSessionState(): UnauthorizedSessionState {
  return state
}
