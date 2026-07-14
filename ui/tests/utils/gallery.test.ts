import { describe, expect, it } from 'bun:test';
import { galleryFiles, hasGalleryFiles } from '~/utils/gallery';

describe('gallery utils', () => {
  it('returns only valid files for gallery-dl items', () => {
    const item = {
      downloader: 'gallery-dl',
      extras: {
        gallery_files: [
          { filename: 'post/image.jpg', size: 10, media_type: 'image', mimetype: 'image/jpeg' },
          { filename: '', size: 0, media_type: 'file', mimetype: 'application/octet-stream' },
        ],
      },
    } as StoreItem;
    expect(galleryFiles(item)).toHaveLength(1);
    expect(hasGalleryFiles(item)).toBe(true);
  });

  it('does not treat yt-dlp sidecars as a gallery', () => {
    expect(
      galleryFiles({ downloader: 'yt-dlp', extras: { gallery_files: [] } } as StoreItem),
    ).toEqual([]);
  });
});
