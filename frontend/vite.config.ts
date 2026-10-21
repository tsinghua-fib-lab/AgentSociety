import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
    server: {
        proxy: {
            '/api/alipay': {
                target: 'https://agentsociety.fiblab.net',
                changeOrigin: true,
            },
            '/api': {
                target: 'http://localhost:80',
                changeOrigin: true,
            }
        }
    },
    plugins: [react()],
    base: '/',
    build: {
        outDir: 'dist',
        assetsDir: 'assets',
        sourcemap: false,
    }
})
