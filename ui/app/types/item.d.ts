export type item_request = {
  /** Unique identifier for the item */
  id?: string | null;
  /** URL of the item to download */
  url: string;
  /** Preset to use for the download */
  preset?: string;
  /** Where to save the downloaded item */
  folder?: string;
  /** Output template for the downloaded item */
  template?: string;
  /** Additional command line options for the selected download engine */
  cli?: string;
  /** Cookies file for the download */
  cookies?: string;
  /** Auto start the download */
  auto_start?: boolean;
  /** Download engine. Omitted requests continue to use yt-dlp. */
  downloader?: 'yt-dlp' | 'gallery-dl';
  /** Extras data for the item */
  extras?: Record<string, any>;
};
