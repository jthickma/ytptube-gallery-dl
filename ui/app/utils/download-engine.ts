import { request, ensure_api_success } from '~/utils';
import type { DownloadEngine, item_request } from '~/types/item';

export const detectDownloadEngine = async (
  item: Partial<Omit<item_request, 'id'>>,
): Promise<DownloadEngine> => {
  if (item.engine && item.engine !== 'auto') return item.engine;
  const response = await request('/api/gallery-dl/detect/', {
    method: 'POST',
    body: JSON.stringify(item),
  });
  await ensure_api_success(response);
  return (await response.json()).engine;
};

export const convertGalleryOptions = async (args: string): Promise<Record<string, any>> => {
  const response = await request('/api/gallery-dl/convert/', {
    method: 'POST',
    body: JSON.stringify({ args }),
  });
  await ensure_api_success(response);
  return (await response.json()).options;
};
