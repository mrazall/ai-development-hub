import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({ base: './', cacheDir: '/tmp/aihub-desktop-ui-vite', plugins: [react()], build: { outDir: 'dist' }, test: { environment: 'jsdom', setupFiles: './src/test-setup.ts', globals: true } });
