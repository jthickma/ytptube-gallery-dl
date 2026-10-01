<template>
  <div class="space-y-4 p-4 sm:p-6">
    <UInput
      v-model="search"
      :placeholder="t('common.search')"
      class="w-full"
      icon="i-lucide-search"
    />
    <p v-if="error" role="alert" class="text-error">{{ error }}</p>
    <div
      v-for="option in filtered"
      :key="option.flags.join(',')"
      class="border-b border-default py-2"
    >
      <code class="text-primary">{{ option.flags.join(', ') }}</code>
      <p class="text-sm text-toned">{{ option.help }}</p>
    </div>
  </div>
</template>
<script setup lang="ts">
import { request, ensure_api_success } from '~/utils';
const { t } = useI18n();
const search = ref('');
const error = ref('');
const options = ref<Array<{ flags: string[]; help: string }>>([]);
const filtered = computed(() =>
  options.value.filter((option) =>
    `${option.flags.join(' ')} ${option.help}`.toLowerCase().includes(search.value.toLowerCase()),
  ),
);
onMounted(async () => {
  try {
    const response = await request('/api/gallery-dl/options/');
    await ensure_api_success(response);
    options.value = (await response.json()).options;
  } catch (cause) {
    error.value = String(cause);
  }
});
</script>
