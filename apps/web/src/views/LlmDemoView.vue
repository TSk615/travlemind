<script setup lang="ts">
import { computed, reactive, ref } from "vue"
import type { LlmWireApi } from "@travelmind/shared-types"

interface ChatMessage {
  role: "user" | "assistant" | "error"
  content: string
}

interface DemoConfig {
  base_url: string
  api_key: string
  model: string
  wire_api: LlmWireApi
  system_prompt: string
}

const DEMO_STORAGE_KEY = "travelmind.llm.demo"
const SHARED_STORAGE_KEY = "travelmind.llm.settings"

const form = reactive<DemoConfig>({
  base_url: "https://new.xychatai.com/codex/v1",
  api_key: "",
  model: "gpt-5.4",
  wire_api: "responses",
  system_prompt: "You are a helpful travel planning assistant. Reply briefly and clearly."
})

const input = ref("Hello, please say hi and confirm you can respond normally.")
const sending = ref(false)
const errorText = ref("")
const rawRequest = ref("")
const rawResponse = ref("")
const messages = ref<ChatMessage[]>([])

bootstrap()

const canSend = computed(() => {
  return Boolean(!sending.value && form.base_url.trim() && form.api_key.trim() && form.model.trim() && input.value.trim())
})

function bootstrap() {
  if (typeof window === "undefined") {
    return
  }

  try {
    const raw = window.localStorage.getItem(DEMO_STORAGE_KEY) || window.localStorage.getItem(SHARED_STORAGE_KEY)
    if (!raw) {
      return
    }
    const parsed = JSON.parse(raw) as Partial<DemoConfig>
    form.base_url = String(parsed.base_url ?? form.base_url)
    form.api_key = String(parsed.api_key ?? form.api_key)
    form.model = String(parsed.model ?? form.model)
    form.wire_api = parsed.wire_api === "chat_completions" ? "chat_completions" : "responses"
    form.system_prompt = String(parsed.system_prompt ?? form.system_prompt)
  } catch {
    // Ignore local storage errors.
  }
}

function persistConfig() {
  if (typeof window === "undefined") {
    return
  }

  try {
    const serialized = JSON.stringify(form)
    window.localStorage.setItem(DEMO_STORAGE_KEY, serialized)
    window.localStorage.setItem(SHARED_STORAGE_KEY, serialized)
  } catch {
    // Ignore local storage errors.
  }
}

function clearChat() {
  messages.value = []
  errorText.value = ""
  rawRequest.value = ""
  rawResponse.value = ""
}

async function send() {
  if (!canSend.value) {
    return
  }

  const userText = input.value.trim()
  persistConfig()
  sending.value = true
  errorText.value = ""
  messages.value.push({ role: "user", content: userText })

  const upstreamPayload =
    form.wire_api === "responses"
      ? {
          model: form.model.trim(),
          input: [
            {
              role: "system",
              content: [{ type: "input_text", text: form.system_prompt.trim() }]
            },
            {
              role: "user",
              content: [{ type: "input_text", text: userText }]
            }
          ]
        }
      : {
          model: form.model.trim(),
          messages: [
            { role: "system", content: form.system_prompt.trim() },
            { role: "user", content: userText }
          ]
        }

  const relayPayload = {
    base_url: form.base_url.trim(),
    api_key: form.api_key.trim(),
    wire_api: form.wire_api,
    payload: upstreamPayload
  }

  rawRequest.value = JSON.stringify({ url: "/api/v1/llm/proxy", payload: relayPayload }, null, 2)

  try {
    const response = await fetch("/api/v1/llm/proxy", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(relayPayload)
    })

    const contentType = response.headers.get("content-type") ?? ""
    const rawBody = await response.text()
    rawResponse.value = rawBody

    if (!response.ok) {
      throw new Error(extractErrorMessage(rawBody, response.status))
    }

    const assistantText =
      form.wire_api === "responses"
        ? contentType.includes("text/event-stream")
          ? extractResponsesTextFromSse(rawBody)
          : extractResponsesTextFromJson(rawBody)
        : extractChatTextFromJson(rawBody)

    messages.value.push({ role: "assistant", content: assistantText })
    input.value = ""
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown request failure"
    errorText.value = message
    messages.value.push({ role: "error", content: message })
  } finally {
    sending.value = false
  }
}

function extractErrorMessage(rawBody: string, status: number): string {
  try {
    const parsed = JSON.parse(rawBody) as { error?: { message?: string } | string; message?: string }
    if (typeof parsed.error === "string") return parsed.error
    if (typeof parsed.error?.message === "string") return parsed.error.message
    if (typeof parsed.message === "string") return parsed.message
  } catch {
    // Ignore parse errors.
  }
  return rawBody.trim() || `Request failed with status ${status}`
}

function extractResponsesTextFromJson(rawBody: string): string {
  const body = JSON.parse(rawBody) as any
  if (typeof body.output_text === "string" && body.output_text.trim()) {
    return body.output_text
  }
  const blocks = Array.isArray(body.output)
    ? body.output
        .flatMap((item: any) => Array.isArray(item?.content) ? item.content : [])
        .map((item: any) => item?.text)
        .filter((value: unknown): value is string => typeof value === "string" && value.trim().length > 0)
    : []
  if (blocks.length > 0) {
    return blocks.join("\n")
  }
  throw new Error("Responses API did not return text output")
}

function extractResponsesTextFromSse(rawBody: string): string {
  const lines = rawBody
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data: "))
    .map((line) => line.slice(6))

  let combined = ""
  let completed = ""

  for (const line of lines) {
    if (!line || line === "[DONE]") {
      continue
    }

    let parsed: any
    try {
      parsed = JSON.parse(line)
    } catch {
      continue
    }

    if (parsed.type === "response.output_text.delta" && typeof parsed.delta === "string") {
      combined += parsed.delta
    }

    if (parsed.type === "response.output_text.done" && typeof parsed.text === "string") {
      completed = parsed.text
    }

    if (parsed.type === "response.completed") {
      const blocks = Array.isArray(parsed.response?.output)
        ? parsed.response.output
            .flatMap((item: any) => Array.isArray(item?.content) ? item.content : [])
            .map((item: any) => item?.text)
            .filter((value: unknown): value is string => typeof value === "string" && value.trim().length > 0)
        : []
      if (blocks.length > 0) {
        completed = blocks.join("\n")
      }
    }
  }

  const finalText = completed || combined
  if (!finalText.trim()) {
    throw new Error("Responses API stream did not contain assistant text")
  }
  return finalText
}

function extractChatTextFromJson(rawBody: string): string {
  const body = JSON.parse(rawBody) as any
  const content = body.choices?.[0]?.message?.content
  if (typeof content === "string" && content.trim()) {
    return content
  }
  if (Array.isArray(content)) {
    const blocks = content
      .map((item: any) => item?.text)
      .filter((value: unknown): value is string => typeof value === "string" && value.trim().length > 0)
    if (blocks.length > 0) {
      return blocks.join("\n")
    }
  }
  throw new Error("Chat Completions API did not return message content")
}
</script>

<template>
  <div class="llm-demo-page">
    <section class="llm-demo-shell">
      <aside class="llm-demo-sidebar">
        <div>
          <p class="llm-demo-kicker">LLM demo</p>
          <h1>Third-party model test bench</h1>
          <p class="llm-demo-muted">This page is isolated from the trip workflow and only tests whether the browser can call the configured third-party endpoint through the relay.</p>
        </div>

        <div class="llm-demo-form">
          <label>
            Base URL
            <input v-model="form.base_url" placeholder="https://new.xychatai.com/codex/v1" />
          </label>
          <label>
            Model
            <input v-model="form.model" placeholder="gpt-5.4" />
          </label>
          <label>
            API format
            <select v-model="form.wire_api">
              <option value="responses">Responses API</option>
              <option value="chat_completions">Chat Completions API</option>
            </select>
          </label>
          <label>
            API Key
            <input v-model="form.api_key" type="password" autocomplete="off" placeholder="sk-..." />
          </label>
          <label>
            System prompt
            <textarea v-model="form.system_prompt"></textarea>
          </label>
        </div>

        <div class="llm-demo-actions">
          <button class="primary" type="button" :disabled="!canSend" @click="send">{{ sending ? 'Sending...' : 'Send test message' }}</button>
          <button type="button" @click="clearChat">Clear</button>
        </div>

        <p v-if="errorText" class="llm-demo-error">{{ errorText }}</p>
      </aside>

      <main class="llm-demo-main">
        <section class="llm-demo-panel">
          <h2>Chat</h2>
          <div class="llm-demo-chat">
            <div v-if="messages.length === 0" class="llm-demo-empty">No messages yet. Click send to test the endpoint.</div>
            <article v-for="(message, index) in messages" :key="`${message.role}-${index}`" :class="['llm-demo-message', `llm-demo-message--${message.role}`]">
              <header>{{ message.role }}</header>
              <pre>{{ message.content }}</pre>
            </article>
          </div>
          <div class="llm-demo-composer">
            <textarea v-model="input" placeholder="Say hello and ask the model to confirm it can respond."></textarea>
          </div>
        </section>

        <section class="llm-demo-panel">
          <h2>Raw request</h2>
          <pre>{{ rawRequest || 'No request yet.' }}</pre>
        </section>

        <section class="llm-demo-panel">
          <h2>Raw response</h2>
          <pre>{{ rawResponse || 'No response yet.' }}</pre>
        </section>
      </main>
    </section>
  </div>
</template>

<style scoped>
.llm-demo-page {
  min-height: 100vh;
  padding: 24px;
  background: linear-gradient(135deg, #f8f4ee 0%, #f4efe6 100%);
}

.llm-demo-shell {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 20px;
}

.llm-demo-sidebar,
.llm-demo-panel {
  background: rgba(255, 252, 247, 0.92);
  border: 1px solid rgba(30, 28, 23, 0.12);
  border-radius: 24px;
  box-shadow: 0 18px 40px rgba(54, 41, 20, 0.12);
  padding: 24px;
}

.llm-demo-kicker {
  margin: 0 0 8px;
  font-size: 0.8rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #c96d3b;
  font-weight: 800;
}

.llm-demo-muted {
  color: #60574b;
}

.llm-demo-form {
  display: grid;
  gap: 14px;
  margin-top: 24px;
}

.llm-demo-form label {
  display: grid;
  gap: 8px;
  font-weight: 700;
}

.llm-demo-form input,
.llm-demo-form select,
.llm-demo-form textarea,
.llm-demo-composer textarea {
  width: 100%;
  border: 1px solid rgba(30, 28, 23, 0.14);
  border-radius: 16px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.9);
  font: inherit;
}

.llm-demo-form textarea,
.llm-demo-composer textarea {
  min-height: 120px;
  resize: vertical;
}

.llm-demo-actions {
  display: flex;
  gap: 10px;
  margin-top: 20px;
}

.llm-demo-actions button {
  border-radius: 999px;
  padding: 10px 16px;
  border: 1px solid rgba(30, 28, 23, 0.14);
  background: rgba(255, 255, 255, 0.7);
  cursor: pointer;
}

.llm-demo-actions button.primary {
  background: #1e1c17;
  color: white;
}

.llm-demo-error {
  color: #8a2317;
  margin-top: 16px;
  font-weight: 700;
}

.llm-demo-main {
  display: grid;
  gap: 20px;
}

.llm-demo-chat {
  display: grid;
  gap: 12px;
}

.llm-demo-empty {
  color: #60574b;
}

.llm-demo-message {
  border-radius: 18px;
  padding: 14px;
  border: 1px solid rgba(30, 28, 23, 0.12);
}

.llm-demo-message--user {
  background: rgba(13, 122, 111, 0.08);
}

.llm-demo-message--assistant {
  background: rgba(255, 255, 255, 0.8);
}

.llm-demo-message--error {
  background: rgba(255, 226, 223, 0.8);
  border-color: rgba(138, 35, 23, 0.25);
}

.llm-demo-message header {
  font-weight: 800;
  text-transform: uppercase;
  font-size: 0.75rem;
  margin-bottom: 8px;
}

.llm-demo-message pre,
.llm-demo-panel pre {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

@media (max-width: 980px) {
  .llm-demo-shell {
    grid-template-columns: 1fr;
  }
}
</style>
