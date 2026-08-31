import { Routes } from '@angular/router';

import { AppShellComponent } from './shared/layout/app-shell.component';

/**
 * Route table.
 *
 * The landing page sits outside the shell; everything else renders inside it.
 * Feature components are lazy-loaded so the landing page ships on its own.
 */
export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    title: 'CodeOops',
    loadComponent: () =>
      import('./features/landing/landing.component').then((m) => m.LandingComponent),
  },
  {
    path: '',
    component: AppShellComponent,
    children: [
      {
        path: 'dashboard',
        title: 'Dashboard · CodeOops',
        loadComponent: () =>
          import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent),
      },
      {
        path: 'analyze',
        title: 'Analyze repository · CodeOops',
        loadComponent: () =>
          import('./features/repositories/analyze-repository.component').then(
            (m) => m.AnalyzeRepositoryComponent,
          ),
      },
      {
        path: 'jobs',
        title: 'Jobs · CodeOops',
        loadComponent: () =>
          import('./features/jobs/job-list.component').then((m) => m.JobListComponent),
      },
      {
        path: 'jobs/:id',
        title: 'Job progress · CodeOops',
        loadComponent: () =>
          import('./features/jobs/job-progress.component').then((m) => m.JobProgressComponent),
      },
      {
        path: 'documentation',
        title: 'Documentation · CodeOops',
        loadComponent: () =>
          import('./features/documentation/documentation-index.component').then(
            (m) => m.DocumentationIndexComponent,
          ),
      },
      {
        path: 'documentation/:id',
        title: 'Overview · CodeOops',
        loadComponent: () =>
          import('./features/documentation/documentation-viewer.component').then(
            (m) => m.DocumentationViewerComponent,
          ),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
