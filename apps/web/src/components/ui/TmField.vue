<script setup lang="ts">
import { computed } from "vue"
import TmInlineHint from "./TmInlineHint.vue"

const props = withDefaults(
  defineProps<{
    modelValue: string | number
    label: string
    id: string
    type?: "text" | "number" | "date" | "email" | "password" | "url"
    placeholder?: string
    hint?: string
    error?: string
    required?: boolean
    disabled?: boolean
    min?: string | number
    max?: string | number
    minlength?: number
  }>(),
  {
    type: "text",
    placeholder: "",
    hint: "",
    error: "",
    required: false,
    disabled: false,
    min: undefined,
    max: undefined,
    minlength: undefined
  }
)

const emit = defineEmits<{
  "update:modelValue": [value: string | number]
}>()

const hintId = computed(() => props.hint || props.error ? `${props.id}-hint` : undefined)

function onInput(event: Event) {
  const target = event.target as HTMLInputElement
  const value = props.type === "number" ? Number(target.value) : target.value
  emit("update:modelValue", value)
}
</script>

<template>
  <div :class="['tm-field', { 'tm-field--error': !!props.error, 'tm-field--disabled': props.disabled }]">
    <label :for="props.id" class="tm-field__label">
      {{ props.label }}
      <span v-if="props.required" class="tm-field__required" aria-hidden="true">*</span>
    </label>
    <input
      :id="props.id"
      :type="props.type"
      :value="props.modelValue"
      :placeholder="props.placeholder"
      :required="props.required"
      :disabled="props.disabled"
      :min="props.min"
      :max="props.max"
      :minlength="props.minlength"
      :aria-describedby="hintId"
      :aria-invalid="!!props.error"
      class="tm-field__input"
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
.tm-field {
  display: flex;
  flex-direction: column;
  gap: var(--tm-space-2);
}

.tm-field__label {
  font-size: var(--tm-text-sm);
  font-weight: 700;
  color: var(--tm-tea);
}

.tm-field__required {
  color: var(--tm-error);
  margin-left: 2px;
}

.tm-field__input {
  width: 100%;
  padding: var(--tm-space-3) var(--tm-space-4);
  border: none;
  border-radius: var(--tm-radius-md);
  background-color: var(--tm-snow);
  box-shadow: var(--tm-shadow-inset-sm);
  font-family: var(--tm-font-body);
  font-size: var(--tm-text-base);
  color: var(--tm-tea);
  transition:
    box-shadow var(--tm-duration-fast) var(--tm-ease-out),
    background-color var(--tm-duration-fast) var(--tm-ease-out);
}

.tm-field__input::placeholder {
  color: var(--tm-stone);
  opacity: 0.7;
}

.tm-field__input:hover:not(:disabled) {
  background-color: #ffffff;
}

.tm-field__input:focus {
  outline: none;
  box-shadow:
    var(--tm-shadow-inset-sm),
    0 0 0 3px rgba(93, 122, 99, 0.12);
}

.tm-field--error .tm-field__input {
  box-shadow:
    var(--tm-shadow-inset-sm),
    0 0 0 3px rgba(199, 91, 74, 0.12);
}

.tm-field--disabled .tm-field__label {
  opacity: 0.5;
}

.tm-field__input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
