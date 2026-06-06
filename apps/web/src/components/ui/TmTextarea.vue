<script setup lang="ts">
import { computed } from "vue"
import TmInlineHint from "./TmInlineHint.vue"

const props = withDefaults(
  defineProps<{
    modelValue: string
    label: string
    id: string
    placeholder?: string
    hint?: string
    error?: string
    required?: boolean
    disabled?: boolean
    rows?: number
  }>(),
  {
    placeholder: "",
    hint: "",
    error: "",
    required: false,
    disabled: false,
    rows: 4
  }
)

const emit = defineEmits<{
  "update:modelValue": [value: string]
}>()

const hintId = computed(() => props.hint || props.error ? `${props.id}-hint` : undefined)

function onInput(event: Event) {
  const target = event.target as HTMLTextAreaElement
  emit("update:modelValue", target.value)
}
</script>

<template>
  <div :class="['tm-textarea', { 'tm-textarea--error': !!props.error, 'tm-textarea--disabled': props.disabled }]">
    <label :for="props.id" class="tm-textarea__label">
      {{ props.label }}
      <span v-if="props.required" class="tm-textarea__required" aria-hidden="true">*</span>
    </label>
    <textarea
      :id="props.id"
      :value="props.modelValue"
      :placeholder="props.placeholder"
      :required="props.required"
      :disabled="props.disabled"
      :rows="props.rows"
      :aria-describedby="hintId"
      :aria-invalid="!!props.error"
      class="tm-textarea__input"
      @input="onInput"
    />
    <TmInlineHint
      v-if="props.error"
      :id="hintId"
      :message="props.error"
      variant="error"
    />
    <TmInlineHint
      v-else-if="props.hint"
      :id="hintId"
      :message="props.hint"
      variant="hint"
    />
  </div>
</template>

<style scoped>
.tm-textarea {
  display: flex;
  flex-direction: column;
  gap: var(--tm-space-2);
}

.tm-textarea__label {
  font-size: var(--tm-text-sm);
  font-weight: 700;
  color: var(--tm-tea);
}

.tm-textarea__required {
  color: var(--tm-error);
  margin-left: 2px;
}

.tm-textarea__input {
  width: 100%;
  padding: var(--tm-space-3) var(--tm-space-4);
  border: none;
  border-radius: var(--tm-radius-md);
  background-color: var(--tm-paper);
  box-shadow: var(--tm-shadow-inset-md);
  font-family: var(--tm-font-body);
  font-size: var(--tm-text-base);
  color: var(--tm-tea);
  resize: vertical;
  min-height: 100px;
  transition:
    box-shadow var(--tm-duration-fast) var(--tm-ease-out),
    background-color var(--tm-duration-fast) var(--tm-ease-out);
}

.tm-textarea__input::placeholder {
  color: var(--tm-stone);
  opacity: 0.7;
}

.tm-textarea__input:hover:not(:disabled) {
  background-color: #e9edf2;
}

.tm-textarea__input:focus {
  outline: none;
  box-shadow:
    var(--tm-shadow-inset-lg),
    var(--tm-focus-ring);
}

.tm-textarea--error .tm-textarea__input {
  box-shadow:
    var(--tm-shadow-inset-md),
    0 0 0 3px rgba(234, 67, 53, 0.16);
}

.tm-textarea--disabled .tm-textarea__label {
  opacity: 0.5;
}

.tm-textarea__input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
