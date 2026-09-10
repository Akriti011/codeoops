import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/**
 * Single inline-SVG icon set. Avoids an icon dependency and keeps every glyph
 * on the same 20x20 grid and 1.6 stroke weight, which is what makes an icon
 * set look like one set.
 */
export type IconName =
  | 'dashboard' | 'repositories' | 'jobs' | 'documentation' | 'workflows'
  | 'settings' | 'users' | 'logs' | 'search' | 'bell' | 'menu' | 'chevron-down'
  | 'chevron-right' | 'plus' | 'upload' | 'git' | 'download' | 'refresh'
  | 'check' | 'x' | 'alert' | 'clock' | 'play' | 'arrow-right' | 'shield'
  | 'lock' | 'team' | 'bolt' | 'cpu' | 'sitemap' | 'server' | 'file'
  | 'folder' | 'code' | 'external' | 'logout' | 'support' | 'sun' | 'trash';

const PATHS: Record<IconName, string> = {
  dashboard: 'M3 3h6v7H3zM11 3h6v4h-6zM11 11h6v6h-6zM3 14h6v3H3z',
  repositories: 'M3 6.2 10 2.6l7 3.6-7 3.6zM3 10l7 3.6 7-3.6M3 13.8 10 17.4l7-3.6',
  jobs: 'M4 5h12v10H4zM7 3v4M13 3v4M7 10h6M7 13h4',
  documentation: 'M5 3h7l3 3v11H5zM12 3v3h3M7.5 10h5M7.5 13h3.5',
  workflows: 'M5 4.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM15 18.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM15 4.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM5 4.5v6a3 3 0 0 0 3 3h4M15 4.5v1a3 3 0 0 1-3 3H8',
  settings: 'M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM10 2.5v2M10 15.5v2M17.5 10h-2M4.5 10h-2M15.3 4.7l-1.4 1.4M6.1 13.9l-1.4 1.4M15.3 15.3l-1.4-1.4M6.1 6.1 4.7 4.7',
  users: 'M13 16v-1.5a3 3 0 0 0-3-3H6a3 3 0 0 0-3 3V16M8 8.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM17 16v-1.5a3 3 0 0 0-2.2-2.9M13 3.7a3 3 0 0 1 0 5.8',
  logs: 'M4 4h12v12H4zM7 8h6M7 11h6M7 14h3',
  search: 'M9 15A6 6 0 1 0 9 3a6 6 0 0 0 0 12zM17 17l-3.8-3.8',
  bell: 'M15 7a5 5 0 0 0-10 0c0 5-2 6-2 6h14s-2-1-2-6M11.7 16a2 2 0 0 1-3.4 0',
  menu: 'M3 6h14M3 10h14M3 14h14',
  'chevron-down': 'M6 8l4 4 4-4',
  'chevron-right': 'M8 6l4 4-4 4',
  plus: 'M10 4v12M4 10h12',
  upload: 'M10 13V4M6.5 7.5 10 4l3.5 3.5M4 13v2a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-2',
  git: 'M6 5.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM6 17.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM14 8.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM6 5.5v9M14 8.5v1a3 3 0 0 1-3 3H6',
  download: 'M10 4v9M6.5 9.5 10 13l3.5-3.5M4 15v1a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-1',
  refresh: 'M16 5v4h-4M4 15v-4h4M4.6 8a6 6 0 0 1 10-2.2L16 7M15.4 12a6 6 0 0 1-10 2.2L4 13',
  check: 'M4.5 10.5 8 14l7.5-8',
  x: 'M5 5l10 10M15 5L5 15',
  alert: 'M10 7v4M10 14h.01M10 3 2.5 16.5h15z',
  clock: 'M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM10 6v4l2.5 1.5',
  play: 'M7 5l8 5-8 5z',
  'arrow-right': 'M4 10h11M11 6l4 4-4 4',
  shield: 'M10 17s6-2.5 6-7V5l-6-2-6 2v5c0 4.5 6 7 6 7z',
  lock: 'M5 9h10v8H5zM7.5 9V6.5a2.5 2.5 0 0 1 5 0V9',
  team: 'M13 16v-1.5a3 3 0 0 0-3-3H6a3 3 0 0 0-3 3V16M8 8.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM17 16v-1.5a3 3 0 0 0-2.2-2.9',
  bolt: 'M11 2 4 11h5l-1 7 7-9h-5z',
  cpu: 'M6 6h8v8H6zM8 3v3M12 3v3M8 14v3M12 14v3M3 8h3M3 12h3M14 8h3M14 12h3',
  sitemap: 'M8 3h4v3H8zM3 14h4v3H3zM13 14h4v3h-4zM10 6v4M5 14v-2h10v2M10 10v2',
  server: 'M3 4h14v4H3zM3 12h14v4H3zM6 6h.01M6 14h.01',
  file: 'M5 3h7l3 3v11H5zM12 3v3h3',
  folder: 'M3 5.5h5l1.5 2H17V16H3z',
  code: 'M7 6.5 3.5 10 7 13.5M13 6.5 16.5 10 13 13.5',
  external: 'M12 4h4v4M16 4l-6 6M14 11v4a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4',
  logout: 'M8 17H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h3M13 13.5 16.5 10 13 6.5M16.5 10H8',
  support: 'M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM8 8a2 2 0 1 1 2.6 1.9c-.4.2-.6.5-.6.9v.7M10 14h.01',
  sun: 'M10 13.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM10 2v1.5M10 16.5V18M18 10h-1.5M3.5 10H2M15.7 4.3l-1 1M5.3 14.7l-1 1M15.7 15.7l-1-1M5.3 5.3l-1-1',
  trash: 'M4 6h12M8 6V4h4v2M6 6l.8 10a1 1 0 0 0 1 1h4.4a1 1 0 0 0 1-1L14 6M9 9v5M11 9v5',
};

const FILLED = new Set<IconName>(['play', 'bolt']);

@Component({
  selector: 'co-icon',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      class="icon"
      viewBox="0 0 20 20"
      [attr.fill]="filled() ? 'currentColor' : 'none'"
      [attr.stroke]="filled() ? 'none' : 'currentColor'"
      stroke-width="1.6"
      stroke-linecap="round"
      stroke-linejoin="round"
      [attr.aria-hidden]="label() ? null : 'true'"
      [attr.role]="label() ? 'img' : null"
      [attr.aria-label]="label()"
    >
      <path [attr.d]="path()" />
    </svg>
  `,
  styles: `
    :host { display: inline-flex; }
    .icon { width: 100%; height: 100%; }
  `,
})
export class IconComponent {
  readonly name = input.required<IconName>();
  /** Set only when the icon carries meaning on its own. */
  readonly label = input<string | null>(null);

  protected readonly path = computed(() => PATHS[this.name()] ?? '');
  protected readonly filled = computed(() => FILLED.has(this.name()));
}
