import { defineConfig } from 'vitest/config';

export default defineConfig({
  base: './',
  build: {
    cssTarget: 'safari14',
    rollupOptions: {
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: '[name].js',
        assetFileNames: '[name][extname]'
      }
    }
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts']
  },
  server: {
    fs: {
      allow: ['..']
    }
  }
});
