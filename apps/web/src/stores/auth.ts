import { defineStore } from "pinia"
import type { User } from "@travelmind/shared-types"
import { api, getErrorMessage } from "@/lib/api"

interface AuthState {
  user: User | null
  initialized: boolean
  bootstrapping: boolean
  pending: boolean
  error: string | null
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    user: null,
    initialized: false,
    bootstrapping: false,
    pending: false,
    error: null
  }),
  actions: {
    clearError() {
      this.error = null
    },
    async bootstrap() {
      if (this.initialized || this.bootstrapping) {
        return
      }
      this.bootstrapping = true
      this.error = null
      try {
        // A missing session is a normal startup case, so bootstrap should not
        // surface it as a user-facing error banner.
        this.user = await api.me()
      } catch {
        this.user = null
      } finally {
        this.initialized = true
        this.bootstrapping = false
      }
    },
    async login(email: string, password: string) {
      this.pending = true
      this.error = null
      try {
        this.user = await api.login({ email, password })
      } catch (error) {
        this.error = getErrorMessage(error, "Login failed")
        throw error
      } finally {
        this.pending = false
      }
    },
    async register(name: string, email: string, password: string) {
      this.pending = true
      this.error = null
      try {
        this.user = await api.register({ name, email, password })
      } catch (error) {
        this.error = getErrorMessage(error, "Register failed")
        throw error
      } finally {
        this.pending = false
      }
    },
    async logout() {
      this.pending = true
      this.error = null
      try {
        await api.logout()
      } finally {
        // Always clear the local session after a logout attempt to keep the UI
        // consistent with the intent, even if the server-side session is gone.
        this.user = null
        this.pending = false
      }
    }
  }
})
