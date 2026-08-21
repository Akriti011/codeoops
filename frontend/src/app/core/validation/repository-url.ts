/**
 * Client-side repository URL check.
 *
 * This exists purely to give fast inline feedback. The backend's
 * `RepositoryUrlPolicy` remains the authority: anything that passes here is
 * still validated server-side, and a server rejection is always surfaced.
 */

const GITHUB_REPO = /^https:\/\/(www\.)?github\.com\/[A-Za-z0-9][\w.-]*\/[A-Za-z0-9][\w.-]*\/?$/;

export interface UrlCheck {
  readonly valid: boolean;
  readonly message?: string;
}

export function checkRepositoryUrl(rawValue: string): UrlCheck {
  const value = rawValue.trim();

  if (!value) {
    return { valid: false, message: 'Enter a GitHub repository URL.' };
  }
  if (!value.startsWith('https://')) {
    return { valid: false, message: 'The URL must start with https://' };
  }
  if (value.includes('@')) {
    return { valid: false, message: 'Remove credentials from the URL.' };
  }
  if (!GITHUB_REPO.test(stripGitSuffix(value))) {
    return {
      valid: false,
      message: 'Use the form https://github.com/owner/repository',
    };
  }
  return { valid: true };
}

function stripGitSuffix(value: string): string {
  return value.replace(/\.git\/?$/, '');
}
