<template>
  <div v-if="config.app.gallerydl_enabled" class="space-y-3">
    <UFormField :label="t('gallery.engine')" :description="t('gallery.engineHelp')">
      <USelect v-model="engine" :items="engines" class="w-full sm:max-w-sm" />
    </UFormField>
    <UFormField
      v-if="engine !== 'ytdlp'"
      :label="t('gallery.options')"
      :description="t('gallery.optionsHelp')"
    >
      <UTextarea
        v-model="gallerydl"
        dir="ltr"
        :rows="3"
        class="w-full"
        placeholder="--write-metadata -o videos=true"
      />
      <NuxtLink
        to="https://gdl-org.github.io/docs/configuration.html"
        target="_blank"
        class="text-sm text-primary hover:underline"
        >{{ t('gallery.documentation') }}</NuxtLink
      >
    </UFormField>
    <p v-if="engine === 'gallerydl'" class="text-sm text-toned">{{ t('gallery.templateHelp') }}</p>
  </div>
</template>

<script setup lang="ts">
import type { DownloadEngine } from '~/types/item';
const { t } = useI18n();
const config = useYtpConfig();
const engine = defineModel<DownloadEngine>('engine', { default: 'auto' });
const gallerydl = defineModel<string>('gallerydl', { default: '' });
const engines = computed(() => [
  { label: t('gallery.auto'), value: 'auto' },
  { label: 'yt-dlp', value: 'ytdlp' },
  { label: 'gallery-dl', value: 'gallerydl' },
]);
</script>
