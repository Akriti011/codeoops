import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { RepositorySubmitFormComponent } from '../repositories/repository-submit-form.component';
import { PipelineVisualComponent } from '../../shared/ui/pipeline-visual.component';
import { SiteHeaderComponent } from '../../shared/layout/site-header.component';

interface Feature {
  readonly title: string;
  readonly copy: string;
  readonly icon: string;
}

interface PipelineStage {
  readonly name: string;
  readonly role: string;
  readonly live: boolean;
}

@Component({
  selector: 'co-home',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    SiteHeaderComponent,
    PipelineVisualComponent,
    RepositorySubmitFormComponent,
  ],
  templateUrl: './home.component.html',
  styleUrl: './home.component.scss',
})
export class HomeComponent {
  protected readonly features: readonly Feature[] = [
    {
      title: 'Repository Analysis',
      copy: 'Point CodeOops at a repository and it becomes a tracked unit of work with a stable identity.',
      icon: 'M3 6.2 10 2.6l7 3.6-7 3.6zM3 10l7 3.6 7-3.6M3 13.8 10 17.4l7-3.6',
    },
    {
      title: 'Architecture Documentation',
      copy: 'Subsystem boundaries and how they compose — written by the documentation engine, not by us.',
      icon: 'M4 16V7l6-4 6 4v9M4 16h12M8 16v-4h4v4',
    },
    {
      title: 'Code Structure',
      copy: 'Module trees and per-module pages, navigable from a single workspace.',
      icon: 'M7 4H4v3h3zM16 4h-3v3h3zM11.5 13h-3v3h3zM5.5 7v3h9V7M10 10v3',
    },
    {
      title: 'Dependency Understanding',
      copy: 'Internal and external relationships surfaced as a graph you can actually read.',
      icon: 'M6 6.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM14 17.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM15 6.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 6.5v5a4 4 0 0 0 4 4h2M15 6.5v1a4 4 0 0 1-4 4H8',
    },
  ];

  protected readonly pipeline: readonly PipelineStage[] = [
    { name: 'Angular', role: 'Workspace UI', live: true },
    { name: 'FastAPI', role: 'Orchestration API', live: true },
    { name: 'Documentation Provider', role: 'Engine boundary', live: true },
    { name: 'CodeWiki', role: 'Documentation engine', live: false },
  ];
}
