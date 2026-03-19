import { createRouter, createWebHistory } from "vue-router"
import HomeView from "@/views/HomeView.vue"
import LoginView from "@/views/LoginView.vue"
import TripsView from "@/views/TripsView.vue"
import NewTripView from "@/views/NewTripView.vue"
import TripDetailView from "@/views/TripDetailView.vue"
import ExportView from "@/views/ExportView.vue"
import { useAuthStore } from "@/stores/auth"

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "home", component: HomeView },
    { path: "/login", name: "login", component: LoginView },
    { path: "/trips", name: "trips", component: TripsView, meta: { requiresAuth: true } },
    { path: "/trips/new", name: "trip-new", component: NewTripView, meta: { requiresAuth: true } },
    { path: "/trips/:id", name: "trip-detail", component: TripDetailView, meta: { requiresAuth: true } },
    { path: "/exports/:id", name: "export-detail", component: ExportView, meta: { requiresAuth: true } }
  ]
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  // Resolve the cookie-backed session once before the first protected
  // navigation so route guards and page components read the same auth state.
  if (!auth.initialized) {
    await auth.bootstrap()
  }

  if (to.meta.requiresAuth && !auth.user) {
    return { name: "login", query: { redirect: to.fullPath } }
  }

  if (to.name === "login" && auth.user) {
    return { name: "trips" }
  }

  return true
})
