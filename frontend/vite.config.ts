import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      // 客服聊天接口继续转发给Python。
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // 独立前缀避免与Python /api冲突，转发时还原成Java的/api路径。
      '/business-api': {
        target: 'http://127.0.0.1:8081',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/business-api/, '/api'),
      },
    },
  },
});
