import { checkRepositoryUrl } from './repository-url';

describe('checkRepositoryUrl', () => {
  const accepted = [
    'https://github.com/octocat/Hello-World',
    'https://github.com/octocat/Hello-World/',
    'https://github.com/octocat/Hello-World.git',
    'https://www.github.com/angular/angular',
    'https://github.com/Akriti011/india-map-explorer.git',
  ];

  const rejected = [
    '',
    '   ',
    'github.com/octocat/Hello-World',
    'http://github.com/octocat/Hello-World',
    'ssh://git@github.com/octocat/Hello-World',
    'https://user:token@github.com/octocat/Hello-World',
    'https://gitlab.com/octocat/Hello-World',
    'https://github.com/octocat',
    'https://github.com/octocat/Hello-World/tree/main',
  ];

  for (const url of accepted) {
    it(`accepts ${url || '(empty)'}`, () => {
      expect(checkRepositoryUrl(url).valid).toBeTrue();
    });
  }

  for (const url of rejected) {
    it(`rejects ${url || '(empty)'}`, () => {
      const result = checkRepositoryUrl(url);
      expect(result.valid).toBeFalse();
      expect(result.message).toBeTruthy();
    });
  }
});
