<script setup lang="ts">
import { computed } from "vue"
import TmInlineHint from "./TmInlineHint.vue"

interface SelectOption {
  value: string
  label: string
}

const props = withDefaults(
  defineProps<{
    modelValue: string
    label: string
    id: string
    options: SelectOption[]
    placeholder?: string
    hint?: string
    error?: string
    required?: boolean
    disabled?: boolean
  }>(),
  {
    placeholder: "",
    hint: "",
    error: "",
    required: false,
    disabled: false
  }
)

const emit = defineEmits<{
  "update:modelValue": [value: string]
}>()

const hintId = computed(() => props.hint || props.error ? `${props.id}-hint` : undefined)

function onChange(event: Event) {
  const target = event.target as HTMLSelectElement
  emit("update:modelValue", target.value)
}
</script>

<template>
  <div :class="['tm-select', { 'tm-select--error': !!props.error, 'tm-select--disabled': props.disabled }]">
    <label :for="props.id" class="tm-select__label">
      {{ props.label }}
      <span v-if="props.required" class="tm-select__required" aria-hidden="true">*</span>
    </label>
    <div class="tm-select__wrapper">
      <select
        :id="props.id"
        :value="props.modelValue"
        :required="props.required"
        :disabled="props.disabled"
        :aria-describedby="hintId"
        :aria-invalid="!!props.error"
        class="tm-select__input"
        @change="onChange"
      >
        <option v-if="props.placeholder" value="" disabled>{{ props.placeholder }}</option>
        <option v-for="option in props.options" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
      <span class="tm-select__chevron" aria-hidden="true">&#9662;</span>
    </div>
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
.tm-select {
  display: flex;
  flex-direction: column;
  gap: var(--tm-space-2);
}

.tm-select__label {
  font-size: var(--tm-text-sm);
  font-weight: 700;
  color: var(--tm-tea);
}

.tm-select__required {
  color: var(--tm-error);
  margin-left: 2px;
}

.tm-select__wrapper {
  position: relative;
}

.tm-select__input {
  width: 100%;
  padding: var(--tm-space-3) var(--tm-space-8) var(--tm-space-3) var(--tm-space-4);
  border: none;
  border-radius: var(--tm-radius-md);
  background-color: var(--tm-paper);
  box-shadow: var(--tm-shadow-inset-md);
  font-family: var(--tm-font-body);
  font-size: var(--tm-text-base);
  color: var(--tm-tea);
  appearance: none;
  cursor: pointer;
  transition:
    box-shadow var(--tm-duration-fast) var(--tm-ease-out),
    background-color var(--tm-duration-fast) var(--tm-ease-out);
}

.tm-select__input:hover:not(:disabled) {
  background-color: #e9edf2;
}

.tm-select__input:focus {
  outline: none;
  box-shadow:
    var(--tm-shadow-inset-lg),
    var(--tm-focus-ring);
}

.tm-select--error .tm-select__input {
  box-shadow:
    var(--tm-shadow-inset-md),
    0 0 0 3px rgba(234, 67, 53, 0.16);
}

.tm-select__chevron {
  position: absolute;
  right: var(--tm-space-4);
  top: 50%;
  transform: translateY(-50%);
  color: var(--tm-stone);
  pointer-events: none;
  font-size: var(--tm-text-sm);
}

.tm-select--disabled .tm-select__label {
  opacity: 0.5;
}

.tm-select__input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
