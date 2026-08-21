import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    title: "CodeOops — Your code broke. Your docs shouldn't.",
    loadComponent: () =>
      import('./features/home/home.component').then((m) => m.HomeComponent),
  },
  {
    path: 'repositories',
    title: 'Repositories — CodeOops',
    loadComponent: () =>
      import('./features/repositories/repository-list.component').then(
        (m) => m.RepositoryListComponent,
      ),
  },
  {
    path: 'documentation',
    title: 'Documentation workspace — CodeOops',
    loadComponent: () =>
      import('./features/documentation/documentation-workspace.component').then(
        (m) => m.DocumentationWorkspaceComponent,
      ),
  },
  {
    path: 'documentation/:repositoryId',
    title: 'Documentation workspace — CodeOops',
    loadComponent: () =>
      import('./features/documentation/documentation-workspace.component').then(
        (m) => m.DocumentationWorkspaceComponent,
      ),
  },
  {
    path: 'settings',
    title: 'Settings — CodeOops',
    loadComponent: () =>
      import('./features/settings/settings.component').then(
        (m) => m.SettingsComponent,
      ),
  },
  {
    path: '**',
    title: 'Not found — CodeOops',
    loadComponent: () =>
      import('./features/not-found/not-found.component').then(
        (m) => m.NotFoundComponent,
      ),
  },
];
