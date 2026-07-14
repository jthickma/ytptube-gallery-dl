import type { GalleryFile, StoreItem } from '~/types/store';

const galleryFiles = (item: Partial<StoreItem> | null | undefined): GalleryFile[] => {
  if (item?.downloader !== 'gallery-dl' || !Array.isArray(item.extras?.gallery_files)) {
    return [];
  }

  return item.extras.gallery_files.filter(
    (file): file is GalleryFile =>
      Boolean(file) &&
      typeof file.filename === 'string' &&
      file.filename.length > 0 &&
      ['image', 'video', 'audio', 'file'].includes(file.media_type),
  );
};

const hasGalleryFiles = (item: Partial<StoreItem> | null | undefined): boolean =>
  galleryFiles(item).length > 0;

export { galleryFiles, hasGalleryFiles };
