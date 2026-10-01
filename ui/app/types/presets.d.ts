import type { DownloadEngine } from './item';
type Preset = {
  id?: number;
  name: string;
  description: string;
  folder: string;
  template: string;
  cookies: string;
  engine?: DownloadEngine;
  gallerydl?: string;
  cli: string;
  default: boolean;
  /** Higher values sort first. */
  priority: number;
};

type PresetRequest = {
  name: string;
  description?: string;
  folder?: string;
  template?: string;
  cookies?: string;
  engine?: DownloadEngine;
  gallerydl?: string;
  cli?: string;
  priority?: number;
};

export type { Preset, PresetRequest };
