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
    // Plotly's modular CommonJS dependencies use the browser global.
    define: { global: 'globalThis' },
    plugins: [react()],
    base: '/',
    build: {
        outDir: 'dist',
        assetsDir: 'assets',
        sourcemap: false,
        rolldownOptions: {
            output: {
                strictExecutionOrder: true,
                codeSplitting: {
                    groups: [{
                        name: 'vendor',
                        test: /node_modules/,
                        minSize: 100_000,
                        maxSize: 250_000,
                    }],
                },
            },
        },
    }
})
