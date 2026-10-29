import { describe, expect, it } from 'bun:test';
import { computed, effectScope, reactive, ref, toRef } from 'vue';
import { galleryTemplate, useGalleryTemplate } from '~/composables/useGalleryTemplate';

describe('gallery filename templates', () => {
  it('clears the saved yt-dlp override when selecting a gallery preset', () => {
    const scope = effectScope();
    const form = reactive({ preset: 'default', template: '%(title)s.%(ext)s' });
    scope.run(() => {
      useGalleryTemplate(
        toRef(form, 'template'),
        computed(() => form.preset === 'gallery_video'),
      );
    });
    expect(form.template).toBe('%(title)s.%(ext)s');
    form.preset = 'gallery_video';
    expect(form.template).toBe('');
    scope.stop();
  });

  it('repairs persisted gallery forms and later imported task templates', () => {
    const scope = effectScope();
    const template = ref('%(uploader)s/%(title)s.%(ext)s');
    scope.run(() => useGalleryTemplate(template, ref(true)));
    expect(template.value).toBe('');
    template.value = '%(id)s.%(ext)s';
    expect(template.value).toBe('');
    template.value = '{tweet_id}_{num}.{extension}';
    expect(template.value).toBe('{tweet_id}_{num}.{extension}');
    scope.stop();
  });

  it('handles per-URL detection before the debounced form detection finishes', () => {
    const template = '%(title)s.%(ext)s';
    expect(galleryTemplate(template, true)).toBe('');
    expect(galleryTemplate(template, false)).toBe(template);
    expect(galleryTemplate('{tweet_id}_{num}.{extension}', true)).toBe(
      '{tweet_id}_{num}.{extension}',
    );
    expect(galleryTemplate(undefined, true)).toBe('');
  });
});
