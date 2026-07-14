<template>
  <div class="space-y-4 p-2">
    <div class="flex flex-wrap items-center gap-3 rounded-lg border border-default bg-muted/20 p-4">
      <UInput
        v-model="query"
        icon="i-lucide-search"
        placeholder="Filter gallery-dl flags..."
        class="min-w-64 flex-1"
      />
      <UBadge color="info" variant="soft">gallery-dl {{ version }}</UBadge>
    </div>
    <UAlert
      v-if="loading"
      color="info"
      variant="soft"
      icon="i-lucide-loader-circle"
      title="Loading gallery-dl options"
    />
    <div v-else class="max-h-[65vh] overflow-auto rounded-lg border border-default">
      <table class="w-full min-w-180 text-sm">
        <thead class="sticky top-0 bg-elevated text-left text-xs uppercase text-toned">
          <tr>
            <th class="px-3 py-3">Flags</th>
            <th class="px-3 py-3">Group</th>
            <th class="px-3 py-3">Description</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-default">
          <tr
            v-for="entry in filtered"
            :key="entry.flags.join('|')"
            :class="entry.ignored ? 'opacity-55' : ''"
          >
            <td class="px-3 py-3 font-mono">
              <span class="flex flex-wrap gap-1"
                ><UBadge v-for="flag in entry.flags" :key="flag" color="neutral" variant="soft">{{
                  flag
                }}</UBadge></span
              >
            </td>
            <td class="px-3 py-3 whitespace-nowrap">{{ entry.group }}</td>
            <td class="px-3 py-3">
              {{ entry.description
              }}<span v-if="entry.ignored" class="ml-2 text-warning">Managed by YTPTube</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
type GalleryOption = { flags: string[]; description: string; group: string; ignored: boolean };
const loading = ref(true);
const query = ref('');
const version = ref('');
const options = ref<GalleryOption[]>([]);
const filtered = computed(() => {
  const value = query.value.trim().toLowerCase();
  return value
    ? options.value.filter((entry) =>
        [...entry.flags, entry.description, entry.group].some((text) =>
          text.toLowerCase().includes(value),
        ),
      )
    : options.value;
});

onMounted(async () => {
  try {
    const response = await request('/api/gallery-dl/options');
    if (!response.ok) return;
    const data = await response.json();
    version.value = data.version || '';
    options.value = Array.isArray(data.options) ? data.options : [];
  } finally {
    loading.value = false;
  }
});
</script>
