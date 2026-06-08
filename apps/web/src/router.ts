import { createRouter, createWebHistory } from "vue-router"
import HomeView from "@/views/HomeView.vue"
import LoginView from "@/views/LoginView.vue"
import TripsView from "@/views/TripsView.vue"
import NewTripView from "@/views/NewTripView.vue"
import TripDetailView from "@/views/TripDetailView.vue"
import ExportView from "@/views/ExportView.vue"
import AIImageStudioView from "@/views/AIImageStudioView.vue"
import CommunityFeedView from "@/views/CommunityFeedView.vue"
import CommunityPostDetailView from "@/views/CommunityPostDetailView.vue"
import SettingsView from "@/views/SettingsView.vue"
import LlmDemoView from "@/views/LlmDemoView.vue"
import AdminView from "@/views/AdminView.vue"
import { useAuthStore } from "@/stores/auth"

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "home", component: HomeView },
    { path: "/login", name: "login", component: LoginView },
    { path: "/trips", name: "trips", component: TripsView, meta: { requiresAuth: true } },
    { path: "/trips/new", name: "trip-new", component: NewTripView, meta: { requiresAuth: true } },
    {
      path: "/trips/:id",
      name: "trip-detail",
      component: TripDetailView,
      props: (route) => ({
        id: String(route.params.id ?? ""),
        jobId: typeof route.query.jobId === "string" ? route.query.jobId : ""
      }),
      meta: { requiresAuth: true, keepAlive: true }
    },
    { path: "/exports/:id", name: "export-detail", component: ExportView, meta: { requiresAuth: true } },
    { path: "/community", name: "community", component: CommunityFeedView, meta: { requiresAuth: true } },
    {
      path: "/community/:id",
      name: "community-post",
      component: CommunityPostDetailView,
      props: (route) => ({
        id: String(route.params.id ?? "")
      }),
      meta: { requiresAuth: true }
    },
    { path: "/images", name: "images", component: AIImageStudioView, meta: { requiresAuth: true, keepAlive: true } },
    { path: "/settings", name: "settings", component: SettingsView, meta: { requiresAuth: true } },
    { path: "/admin", redirect: "/admin/users", meta: { requiresAuth: true, requiresAdmin: true } },
    { path: "/admin/users", name: "admin-users", component: AdminView, meta: { requiresAuth: true, requiresAdmin: true } },
    { path: "/admin/users/:id", name: "admin-user-detail", component: AdminView, meta: { requiresAuth: true, requiresAdmin: true } },
    { path: "/admin/trips", name: "admin-trips", component: AdminView, meta: { requiresAuth: true, requiresAdmin: true } },
    { path: "/admin/trips/:id", name: "admin-trip-detail", component: AdminView, meta: { requiresAuth: true, requiresAdmin: true } },
    { path: "/admin/community", name: "admin-community", component: AdminView, meta: { requiresAuth: true, requiresAdmin: true } },
    { path: "/admin/community/:id", name: "admin-community-detail", component: AdminView, meta: { requiresAuth: true, requiresAdmin: true } },
    { path: "/admin/jobs", name: "admin-jobs", component: AdminView, meta: { requiresAuth: true, requiresAdmin: true } },
    { path: "/admin/jobs/:id", name: "admin-job-detail", component: AdminView, meta: { requiresAuth: true, requiresAdmin: true } },
    { path: "/llm-demo", name: "llm-demo", component: LlmDemoView, meta: { plainShell: true } }
  ]
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.initialized) {
    await auth.bootstrap()
  }

  if (to.meta.requiresAuth && !auth.user) {
    return { name: "login", query: { redirect: to.fullPath } }
  }

  if (to.meta.requiresAdmin && !auth.user?.is_admin) {
    return { name: "trips" }
  }

  if (to.name === "login" && auth.user) {
    if (to.query.redirect && auth.user.is_admin) {
      return String(to.query.redirect)
    }
    return { name: "trips" }
  }

  return true
})
