import { createRouter, createWebHistory } from "vue-router"
import { useAuthStore } from "@/stores/auth"

const HomeView = () => import("@/views/HomeView.vue")
const LoginView = () => import("@/views/LoginView.vue")
const TripsView = () => import("@/views/TripsView.vue")
const NewTripView = () => import("@/views/NewTripView.vue")
const TripDetailView = () => import("@/views/TripDetailView.vue")
const ExportView = () => import("@/views/ExportView.vue")
const CommunityFeedView = () => import("@/views/CommunityFeedView.vue")
const CommunityPostDetailView = () => import("@/views/CommunityPostDetailView.vue")
const SettingsView = () => import("@/views/SettingsView.vue")
const LlmDemoView = () => import("@/views/LlmDemoView.vue")
const AdminView = () => import("@/views/AdminView.vue")

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "home", component: HomeView },
    // The isolated design preview is omitted entirely from production routes.
    ...(import.meta.env.DEV ? [{ path: "/__preview/journey", name: "journey-preview", component: () => import("@/views/JourneyPreviewView.vue") }] : []),
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
    { path: "/images", redirect: "/trips" },
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
