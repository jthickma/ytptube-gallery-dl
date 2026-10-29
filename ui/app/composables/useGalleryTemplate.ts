import { watch, type Ref } from 'vue';

/** Drop a retained yt-dlp override so gallery-dl can use its preset/native filename. */
export const galleryTemplate = (template: string | undefined, gallery: boolean): string =>
  gallery && template?.includes('%(') ? '' : template || '';

export const useGalleryTemplate = (
  template: Ref<string | undefined>,
  gallery: Ref<boolean>,
): void => {
  watch(
    [template, gallery],
    ([value, isGallery]) => {
      if (isGallery && value?.includes('%(')) template.value = '';
    },
    { immediate: true, flush: 'sync' },
  );
};
