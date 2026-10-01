<template>
  <div class="space-y-4 p-4 sm:p-6">
    <p class="text-sm text-toned">
      {{ t('gallery.fileCount', { count: item.files?.length || 0 }) }}
    </p>
    <div v-if="selected" class="space-y-2">
      <UButton
        color="neutral"
        variant="ghost"
        icon="i-lucide-arrow-left"
        @click="selected = null"
        >{{ t('gallery.back') }}</UButton
      >
      <img
        v-if="selected.mime.startsWith('image/')"
        :src="link(selected)"
        :alt="selected.filename"
        class="mx-auto max-h-[70vh] object-contain"
      />
      <video
        v-else-if="selected.mime.startsWith('video/')"
        :src="link(selected)"
        controls
        class="mx-auto max-h-[70vh]"
      />
      <audio
        v-else-if="selected.mime.startsWith('audio/')"
        :src="link(selected)"
        controls
        class="w-full"
      />
      <a
        :href="link(selected)"
        :download="selected.filename.split('/').pop()"
        class="text-sm text-primary break-all hover:underline"
        >{{ selected.filename }}</a
      >
    </div>
    <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      <button
        v-for="file in visibleFiles"
        :key="file.filename"
        type="button"
        class="rounded-lg border border-default overflow-hidden text-start hover:border-primary focus-visible:outline-primary"
        @click="selected = file"
      >
        <img
          v-if="file.mime.startsWith('image/')"
          :src="link(file)"
          :alt="file.filename"
          loading="lazy"
          class="aspect-square w-full object-cover"
        />
        <div v-else class="aspect-square flex items-center justify-center bg-muted">
          <UIcon
            :name="file.mime.startsWith('video/') ? 'i-lucide-video' : 'i-lucide-file'"
            class="size-10"
          />
        </div>
        <p class="truncate p-2 text-xs" :title="file.filename">
          {{ file.filename.split('/').pop() }}
        </p>
      </button>
    </div>
    <UButton
      v-if="!selected && visibleFiles.length < (item.files?.length || 0)"
      color="neutral"
      variant="outline"
      @click="limit += 80"
      >{{ t('gallery.more') }}</UButton
    >
  </div>
</template>
<script setup lang="ts">
import type { StoreItem } from '~/types/store';
import type { GalleryFile } from '~/types/item';
import { uri } from '~/utils';
const props = defineProps<{ item: StoreItem }>();
const { t } = useI18n();
const selected = ref<GalleryFile | null>(null);
const limit = ref(80);
const visibleFiles = computed(() => (props.item.files || []).slice(0, limit.value));
const link = (file: GalleryFile) =>
  uri(
    '/api/download/' +
      encodeURIComponent([props.item.folder, file.filename].filter(Boolean).join('/')),
  );
watch(
  () => props.item._id,
  () => {
    selected.value = null;
    limit.value = 80;
  },
);
</script>
