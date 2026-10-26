import tseslint from 'typescript-eslint';
export default [
  { ignores: ['dist', 'node_modules', '.cache', 'test-results'] },
  { rules: { 'max-len': ['error', { code: 120, ignoreComments: true, ignoreUrls: true, ignoreStrings: true, ignoreTemplateLiterals: true }] } },
  ...tseslint.configs.recommended,
];
