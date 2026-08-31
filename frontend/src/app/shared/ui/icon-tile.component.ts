import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { IconComponent, IconName } from './icon.component';

export type TileTone = 'red' | 'green' | 'blue' | 'amber' | 'violet' | 'cyan' | 'grey';

/** Rounded square with a tinted background and an icon inside. */
@Component({
  selector: 'co-icon-tile',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    <span class="tile" [attr.data-tone]="tone()" [attr.data-size]="size()">
      <co-icon [name]="name()" />
    </span>
  `,
  styles: `
    :host { display: inline-flex; }

    .tile {
      display: grid;
      place-items: center;
      border-radius: var(--r-md);
      background: var(--tone-bg);
      color: var(--tone-fg);
      flex: none;
    }

    .tile[data-size='sm'] { width: 2rem;   height: 2rem;   co-icon { width: 1rem;    height: 1rem; } }
    .tile[data-size='md'] { width: 2.5rem; height: 2.5rem; co-icon { width: 1.25rem; height: 1.25rem; } }
    .tile[data-size='lg'] { width: 3rem;   height: 3rem;   co-icon { width: 1.5rem;  height: 1.5rem; } }
    .tile[data-size='xl'] { width: 3.5rem; height: 3.5rem; border-radius: var(--r-lg);
      co-icon { width: 1.75rem; height: 1.75rem; } }

    .tile[data-tone='red']    { --tone-bg: var(--red-50);    --tone-fg: var(--red-500); }
    .tile[data-tone='green']  { --tone-bg: var(--ok-50);     --tone-fg: var(--ok-600); }
    .tile[data-tone='blue']   { --tone-bg: var(--info-50);   --tone-fg: var(--info-600); }
    .tile[data-tone='amber']  { --tone-bg: var(--warn-50);   --tone-fg: var(--warn-600); }
    .tile[data-tone='violet'] { --tone-bg: var(--violet-50); --tone-fg: var(--violet-500); }
    .tile[data-tone='cyan']   { --tone-bg: var(--cyan-50);   --tone-fg: var(--cyan-500); }
    .tile[data-tone='grey']   { --tone-bg: var(--grey-100);  --tone-fg: var(--grey-500); }
  `,
})
export class IconTileComponent {
  readonly name = input.required<IconName>();
  readonly tone = input<TileTone>('red');
  readonly size = input<'sm' | 'md' | 'lg' | 'xl'>('md');
}
