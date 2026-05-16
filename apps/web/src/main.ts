import { createApp } from "vue"
import { createPinia } from "pinia"
import App from "./App.vue"
import { router } from "./router"
import "@travelmind/ui/styles.css"
import "./styles/tokens.css"
import "./styles/base.css"
import "./styles/tailwind.css"
import "./styles/legacy.css"

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount("#app")
