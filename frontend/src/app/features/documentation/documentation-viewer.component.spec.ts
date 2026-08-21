import { ComponentFixture, TestBed } from '@angular/core/testing';

import { DocumentationState } from '../../core/models/documentation.model';
import { Repository } from '../../core/models/repository.model';
import { DocumentationViewerComponent } from './documentation-viewer.component';

const REPOSITORY: Repository = {
  id: '11111111-1111-4111-8111-111111111111',
  owner: 'octocat',
  name: 'Hello-World',
  repository_url: 'https://github.com/octocat/Hello-World',
  default_branch: 'main',
  status: 'READY',
  created_at: '2026-08-14T10:00:00Z',
  updated_at: '2026-08-14T10:00:00Z',
};

const NOT_GENERATED: DocumentationState = {
  repository_id: REPOSITORY.id,
  status: 'NOT_GENERATED',
  artifact: null,
  detail: 'No documentation provider is connected.',
};

describe('DocumentationViewerComponent', () => {
  let fixture: ComponentFixture<DocumentationViewerComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DocumentationViewerComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(DocumentationViewerComponent);
    fixture.componentRef.setInput('repository', REPOSITORY);
    fixture.componentRef.setInput('state', NOT_GENERATED);
    fixture.detectChanges();
  });

  it('states plainly that no CodeWiki documentation exists', () => {
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('No CodeWiki documentation available.');
  });

  it('renders no document surface when there is no artifact', () => {
    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('.document')).toBeNull();
    expect(host.querySelector('.doc-prose')).toBeNull();
  });

  it('renders no Markdown-derived elements at all', () => {
    const host = fixture.nativeElement as HTMLElement;
    // A stand-in for "no documentation body was fabricated": the reader shows
    // no headings, lists or code blocks beyond its own chrome.
    expect(host.querySelectorAll('pre').length).toBe(0);
    expect(host.querySelectorAll('blockquote').length).toBe(0);
    expect(host.querySelectorAll('table').length).toBe(0);
  });

  it('shows the backend detail so the empty state is explained', () => {
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('No documentation provider is connected.');
  });

  it('reports the engine as not connected', () => {
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('CodeWiki (not connected)');
  });

  it('keeps the architecture visualization empty and labelled', () => {
    const host = fixture.nativeElement as HTMLElement;
    const canvas = host.querySelector('.diagram__canvas');
    expect(canvas).not.toBeNull();
    expect(canvas?.textContent).toContain('nothing to render yet');
  });
});
