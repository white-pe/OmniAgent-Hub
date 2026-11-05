import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, ".", "PAWTEAM_");
  return {
    plugins: [react()],
    build: {
      rolldownOptions: {
        output: {
          // React 运行时独立缓存，避免与工作台组件共用超大首屏分块。
          codeSplitting: {
            groups: [{
              name: "react-vendor",
              test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/,
              priority: 10,
            }],
          },
        },
      },
    },
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target:
            environment.PAWTEAM_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
