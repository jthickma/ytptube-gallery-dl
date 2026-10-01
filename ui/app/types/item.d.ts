export type DownloadEngine = 'auto' | 'ytdlp' | 'gallerydl';
export type GalleryFile = {
  filename: string;
  size: number;
  mime: string;
  metadata?: Record<string, unknown>;
};

export type item_request = {
  id?: string | null;
  url: string;
  engine?: DownloadEngine;
  gallerydl?: string;
  preset?: string;
  folder?: string;
  template?: string;
  cli?: string;
  cookies?: string;
  auto_start?: boolean;
  extras?: Record<string, any>;
};

export type picked_entry = {
  url: string;
  extras: Record<string, unknown>;
};

export type download_form_item = item_request & {
  picked_entries?: picked_entry[];
};
