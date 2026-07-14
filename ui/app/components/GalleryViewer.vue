<template>
  <div class="flex min-h-[60vh] flex-col bg-muted/20">
    <div
      class="flex flex-wrap items-center justify-between gap-3 border-b border-default px-4 py-3"
    >
      <div class="min-w-0">
        <p class="truncate text-sm font-semibold text-highlighted">{{ item.title }}</p>
        <p class="text-xs text-toned">{{ activeIndex + 1 }} of {{ files.length }} media files</p>
      </div>

      <div class="flex items-center gap-2">
        <UButton
          color="neutral"
          variant="outline"
          size="sm"
          icon="i-lucide-chevron-left"
          :disabled="activeIndex === 0"
          aria-label="Previous media"
          @click="
            () => {
              activeIndex -= 1;
            }
          "
        />
        <UButton
          color="neutral"
          variant="outline"
          size="sm"
          icon="i-lucide-chevron-right"
          :disabled="activeIndex >= files.length - 1"
          aria-label="Next media"
          @click="
            () => {
              activeIndex += 1;
            }
          "
        />
        <UButton
          color="neutral"
          variant="outline"
          size="sm"
          icon="i-lucide-download"
          :href="activeUrl"
          external
          :download="activeFile?.filename.split('/').pop()"
          >Download</UButton
        >
      </div>
    </div>

    <div class="flex min-h-[48vh] flex-1 items-center justify-center p-3 sm:p-6">
      <img
        v-if="activeFile?.media_type === 'image'"
        :src="activeUrl"
        :alt="activeFile.filename"
        class="max-h-[70vh] max-w-full rounded-lg object-contain shadow-lg"
      />
      <video
        v-else-if="activeFile?.media_type === 'video'"
        :key="activeUrl"
        :src="activeUrl"
        class="max-h-[70vh] max-w-full rounded-lg bg-black shadow-lg"
        controls
        autoplay
      />
      <div
        v-else-if="activeFile?.media_type === 'audio'"
        class="w-full max-w-2xl rounded-xl border border-default bg-default p-6 shadow-lg"
      >
        <UIcon name="i-lucide-audio-lines" class="mx-auto mb-4 size-14 text-primary" />
        <p class="mb-4 truncate text-center text-sm font-medium">{{ activeFile.filename }}</p>
        <audio :key="activeUrl" :src="activeUrl" class="w-full" controls autoplay />
      </div>
      <UAlert
        v-else
        color="neutral"
        variant="soft"
        icon="i-lucide-file"
        title="Preview unavailable"
        description="This file can be downloaded but cannot be previewed in the browser."
        class="max-w-xl"
      />
    </div>

    <div class="border-t border-default bg-default/80 p-3">
      <div class="flex gap-2 overflow-x-auto pb-1">
        <button
          v-for="(file, index) in files"
          :key="`${file.filename}-${index}`"
          type="button"
          :aria-label="`View ${file.filename}`"
          :class="[
            'flex size-20 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-muted/30 transition-colors',
            index === activeIndex ? 'border-primary ring-2 ring-primary/30' : 'border-default',
          ]"
          @click="activeIndex = index"
        >
          <img
            v-if="file.media_type === 'image'"
            :src="fileUrl(file)"
            :alt="file.filename"
            class="h-full w-full object-cover"
            loading="lazy"
          />
          <UIcon
            v-else
            :name="
              file.media_type === 'video'
                ? 'i-lucide-film'
                : file.media_type === 'audio'
                  ? 'i-lucide-audio-lines'
                  : 'i-lucide-file'
            "
            class="size-7 text-toned"
          />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { GalleryFile, StoreItem } from '~/types/store';
import { galleryFiles } from '~/utils/gallery';

const props = defineProps<{ item: StoreItem }>();
const config = useYtpConfig();
const activeIndex = ref(0);
const files = computed(() => galleryFiles(props.item));
const activeFile = computed(() => files.value[activeIndex.value]);
const fileUrl = (file: GalleryFile): string =>
  makeDownload(config, { folder: props.item.folder, filename: file.filename });
const activeUrl = computed(() => (activeFile.value ? fileUrl(activeFile.value) : ''));

watch(
  () => props.item._id,
  () => {
    activeIndex.value = 0;
  },
);
</script>
